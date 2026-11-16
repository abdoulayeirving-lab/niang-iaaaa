import readline from "node:readline";
import { pathToFileURL } from "node:url";

const pending = new Map();
let activeAgent;
let nextRequestId = 0;

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function requestHost(type, data) {
  const requestId = `r${++nextRequestId}`;
  return new Promise((resolve) => {
    pending.set(requestId, resolve);
    send({ type, requestId, ...data });
  });
}

function schemas(planOnly) {
  const tools = [
    {
      name: "workspace_list_files",
      description: "List accessible project files using relative paths.",
      inputSchema: {
        type: "object",
        properties: { path: { type: "string" } },
        additionalProperties: false,
      },
    },
    {
      name: "workspace_read_file",
      description: "Read a UTF-8 project file using a relative path.",
      inputSchema: {
        type: "object",
        properties: { path: { type: "string" } },
        required: ["path"],
        additionalProperties: false,
      },
    },
    {
      name: "workspace_search",
      description: "Search accessible project text using a relative path.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string" },
          path: { type: "string" },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
  ];
  if (planOnly) return tools;
  return tools.concat([
    {
      name: "workspace_write_file",
      description: "Create or replace a UTF-8 text file inside the selected project.",
      inputSchema: {
        type: "object",
        properties: { path: { type: "string" }, content: { type: "string" } },
        required: ["path", "content"],
        additionalProperties: false,
      },
    },
    {
      name: "workspace_edit_file",
      description: "Replace exact text in an existing project file.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string" },
          find: { type: "string" },
          replace: { type: "string" },
          expected_occurrences: { type: "integer", minimum: 1, maximum: 100 },
        },
        required: ["path", "find", "replace"],
        additionalProperties: false,
      },
    },
    {
      name: "workspace_apply_patch",
      description: "Apply a verified unified diff to existing project files only.",
      inputSchema: {
        type: "object",
        properties: { patch: { type: "string" } },
        required: ["patch"],
        additionalProperties: false,
      },
    },
    {
      name: "workspace_run_check",
      description: "Run one fixed, allowlisted project test, build, or lint check.",
      inputSchema: {
        type: "object",
        properties: {
          check: {
            type: "string",
            enum: [
              "python-tests",
              "python-unittest",
              "python-compile",
              "npm-test",
              "npm-build",
              "npm-lint",
              "git-status",
              "git-diff-check",
            ],
          },
          timeout_seconds: { type: "integer", minimum: 1, maximum: 180 },
        },
        required: ["check"],
        additionalProperties: false,
      },
    },
    {
      name: "workspace_install_dependency",
      description: "Install one named Python or Node dependency in the selected project.",
      inputSchema: {
        type: "object",
        properties: {
          ecosystem: { type: "string", enum: ["python", "node"] },
          package: { type: "string" },
        },
        required: ["ecosystem", "package"],
        additionalProperties: false,
      },
    },
  ]);
}

async function start(message) {
  try {
    const sdk = await import(pathToFileURL(process.env.NIANG_CLINE_AGENT_ENTRY).href);
    const toolDefs = schemas(message.mode === "plan");
    const tools = toolDefs.map((definition) =>
      sdk.createTool({
        ...definition,
        executionMode: "sequential",
        timeoutMs: 180_000,
        execute: async (input, context) =>
          requestHost("tool_request", {
            toolName: definition.name,
            toolCallId: context.toolCallId || "",
            input,
          }),
      }),
    );
    const policies = Object.fromEntries(
      toolDefs.map((definition) => [
        definition.name,
        { enabled: true, autoApprove: definition.name.startsWith("workspace_") &&
            ["workspace_list_files", "workspace_read_file", "workspace_search"].includes(definition.name) },
      ]),
    );
    activeAgent = new sdk.Agent({
      providerId: message.provider_id,
      modelId: message.model_id,
      baseUrl: message.base_url,
      tools,
      toolExecution: "sequential",
      toolPolicies: policies,
      maxIterations: 20,
      systemPrompt: [
        "You are the software-development engine embedded in NIANG IA.",
        `Selected project root: ${message.workspace_root}`,
        `Operating mode: ${message.mode}.`,
        "Only use the supplied workspace tools. Never invent a shell, use external tools, or access paths outside the project.",
        "In plan mode, inspect only and return a plan; no write, command, installation, or deployment tool is available.",
        "Do not request or expose credentials, API keys, environment files, or private keys.",
        "Report which checks were actually run and distinguish unverified suggestions from verified results.",
      ].join("\n"),
      requestToolApproval: async (approval) => {
        const result = await requestHost("approval_request", {
          toolName: approval.toolName,
          toolCallId: approval.toolCallId,
          input: approval.input,
        });
        return { approved: result.approved === true, reason: result.reason || "" };
      },
      logger: {
        debug() {},
        log() {},
        error() {},
      },
    });
    activeAgent.subscribe((event) => {
      if (event.type === "run-failed") {
        send({ type: "agent_event", eventType: event.type, message: event.error?.message || "" });
      } else if (event.type === "status-notice") {
        send({ type: "agent_event", eventType: event.type, message: event.message || "" });
      } else {
        send({ type: "agent_event", eventType: event.type, message: "" });
      }
    });
    const result = await activeAgent.run(message.goal);
    send({
      type: "run_result",
      status: result.status,
      outputText: result.outputText || "",
      iterations: result.iterations,
    });
  } catch (error) {
    send({ type: "fatal", message: error instanceof Error ? error.message : "Cline worker failed." });
  } finally {
    setTimeout(() => process.exit(0), 25);
  }
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  if (!line) continue;
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    send({ type: "fatal", message: "Invalid NDJSON request." });
    continue;
  }
  if (message.type === "start" && !activeAgent) {
    void start(message);
  } else if (message.type === "tool_result" || message.type === "approval_result") {
    const resolve = pending.get(message.requestId);
    if (resolve) {
      pending.delete(message.requestId);
      if (message.type === "tool_result") {
        resolve(message.isError ? `Action failed: ${message.error}` : String(message.output ?? ""));
      } else {
        resolve({ approved: message.approved === true, reason: message.reason || "" });
      }
    }
  } else if (message.type === "cancel") {
    activeAgent?.abort("Mission cancelled by the user.");
  }
}
