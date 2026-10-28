package com.kaizumi.remote

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.Base64

data class GeminiAttachment(val bytes: ByteArray, val mimeType: String, val name: String)

data class NativeAction(val name: String, val arguments: JSONObject)

data class GeminiReply(
    val text: String,
    val modelContent: JSONObject,
    val userContent: JSONObject,
    val action: NativeAction?
)

object GeminiClient {
    private const val MODEL = "gemini-2.5-flash"
    private const val MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
    private const val ENDPOINT =
        "https://generativelanguage.googleapis.com/v1beta/models/$MODEL:generateContent"

    suspend fun generate(
        apiKey: String,
        history: JSONArray,
        prompt: String,
        webSearch: Boolean,
        attachment: GeminiAttachment?
    ): GeminiReply = withContext(Dispatchers.IO) {
        require(prompt.isNotBlank() || attachment != null) { "Écrivez une question ou choisissez un document." }
        require(attachment == null || attachment.bytes.size <= MAX_ATTACHMENT_BYTES) {
            "Le document dépasse la limite de 10 Mo."
        }

        val parts = JSONArray().put(
            JSONObject().put(
                "text",
                prompt.ifBlank { "Résume et analyse le document sélectionné." }
            )
        )
        if (attachment != null) {
            if (attachment.mimeType == "text/plain") {
                parts.put(
                    JSONObject().put(
                        "text",
                        "\n\nDocument sélectionné:\n" +
                            attachment.bytes.toString(Charsets.UTF_8)
                    )
                )
            } else {
                parts.put(
                    JSONObject().put(
                        "inline_data",
                        JSONObject()
                            .put("mime_type", attachment.mimeType)
                            .put("data", Base64.getEncoder().encodeToString(attachment.bytes))
                    )
                )
            }
        }
        val userContent = JSONObject().put("role", "user").put("parts", parts)
        val contents = copyArray(history).put(userContent)
        val candidate = request(apiKey, contents, webSearch)
            .getJSONArray("candidates")
            .getJSONObject(0)
        val content = candidate.getJSONObject("content")
        GeminiReply(
            readText(content, candidate.optJSONObject("groundingMetadata")),
            content,
            userContent,
            readAction(content)
        )
    }

    suspend fun continueAfterAction(
        apiKey: String,
        history: JSONArray,
        modelContent: JSONObject,
        action: NativeAction,
        result: String
    ): String = withContext(Dispatchers.IO) {
        val contents = copyArray(history)
            .put(modelContent)
            .put(
                JSONObject()
                    .put("role", "user")
                    .put(
                        "parts",
                        JSONArray().put(
                            JSONObject().put(
                                "functionResponse",
                                JSONObject()
                                    .put("name", action.name)
                                    .put("response", JSONObject().put("result", result))
                            )
                        )
                    )
            )
        val content = request(apiKey, contents, false, includeFunctions = false)
                .getJSONArray("candidates")
            .getJSONObject(0)
            .getJSONObject("content")
        readText(content)
    }

    private fun request(
        apiKey: String,
        contents: JSONArray,
        webSearch: Boolean,
        includeFunctions: Boolean = true
    ): JSONObject {
        require(apiKey.isNotBlank()) { "Configurez votre clé Gemini dans l’application." }
        val body = JSONObject()
            .put("system_instruction", JSONObject().put("parts", JSONArray().put(JSONObject().put(
                "text",
                "Tu es NIANG IA, un assistant Android honnête et utile. Réponds dans la langue " +
                    "de l'utilisateur. Tu es une IA, jamais un humain. N'affirme pas avoir " +
                    "effectué une action Android avant que le système confirme son résultat. " +
                    "Demande l'autorisation avant toute action sur l'appareil. " +
                    "Ne fabrique jamais de faits, chiffres, dates, citations, sources, " +
                    "liens ou résultats, et ne présente pas une hypothèse comme un fait. " +
                    "N'affirme jamais avoir recherché, lu, exécuté ou vérifié quelque chose " +
                    "sans l'avoir réellement fait. Si tu n'es pas suffisamment sûr, dis : " +
                    "« Je ne connais pas la réponse avec suffisamment de certitude. Je préfère " +
                    "être honnête plutôt que de te donner une information potentiellement " +
                    "fausse. » Demande les précisions manquantes, distingue faits vérifiés, " +
                    "probabilités, hypothèses et inconnues lorsque c'est utile. Pour les faits " +
                    "récents ou importants, utilise la recherche disponible et signale les " +
                    "limites; ne simule jamais une recherche. En programmation, ne prétends " +
                    "pas avoir modifié ou testé du code sans l'avoir fait. Reconnais et corrige " +
                    "clairement tes erreurs, et sois transparent sur tes capacités et accès. " +
                    "Abdoulaye Niang, Sénégalais, étudiant et passionné par l'intelligence " +
                    "artificielle, est l'unique créateur et développeur de NIANG IA. " +
                    "Si l'on demande qui a créé NIANG IA, indique cette identité clairement, " +
                    "dans la langue de la question. Ne prétends pas qu'il a créé le modèle " +
                    "d'IA sous-jacent ou les services tiers."
            ))))
            .put("contents", contents)

        val tools = JSONArray()
        if (includeFunctions) tools.put(functionTool())
        if (webSearch) tools.put(JSONObject().put("google_search", JSONObject()))
        if (tools.length() > 0) body.put("tools", tools)

        val connection = URL(ENDPOINT).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 15_000
            connection.readTimeout = 60_000
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.setRequestProperty("x-goog-api-key", apiKey)
            connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                val detail = runCatching {
                    JSONObject(response).getJSONObject("error").optString("message")
                }.getOrNull().orEmpty()
                throw IllegalStateException(
                    if (detail.isBlank()) "Gemini a répondu avec le code HTTP $status."
                    else "Gemini (HTTP $status) : $detail"
                )
            }
            return JSONObject(response)
        } finally {
            connection.disconnect()
        }
    }

    private fun functionTool(): JSONObject {
        val appCategories = JSONArray(
            listOf(
                "browser", "camera", "calendar", "contacts", "email",
                "settings", "wifi_settings", "bluetooth_settings"
            )
        )
        val appFunction = JSONObject()
            .put("name", "open_android_app")
            .put(
                "description",
                "Open an app or system settings screen from the explicit allowlist."
            )
            .put(
                "parameters",
                JSONObject()
                    .put("type", "OBJECT")
                    .put(
                        "properties",
                        JSONObject().put(
                            "app",
                            JSONObject()
                                .put("type", "STRING")
                                .put("enum", appCategories)
                                .put("description", "App category to open.")
                        )
                    )
                    .put("required", JSONArray().put("app"))
            )
        val alarmFunction = JSONObject()
            .put("name", "set_alarm")
            .put("description", "Ask the Android Clock app to create an alarm.")
            .put(
                "parameters",
                JSONObject()
                    .put("type", "OBJECT")
                    .put(
                        "properties",
                        JSONObject()
                            .put("hour", JSONObject().put("type", "INTEGER"))
                            .put("minute", JSONObject().put("type", "INTEGER"))
                            .put("label", JSONObject().put("type", "STRING"))
                    )
                    .put("required", JSONArray().put("hour").put("minute").put("label"))
            )
        val reminderFunction = JSONObject()
            .put("name", "create_reminder")
            .put("description", "Open the Android calendar event editor for a reminder. Use local ISO date-time.")
            .put(
                "parameters",
                JSONObject()
                    .put("type", "OBJECT")
                    .put(
                        "properties",
                        JSONObject()
                            .put("title", JSONObject().put("type", "STRING"))
                            .put(
                                "date_time",
                                JSONObject().put(
                                    "type",
                                    "STRING"
                                ).put("description", "Local ISO-8601 date-time, for example 2026-11-02T09:30:00.")
                            )
                    )
                    .put("required", JSONArray().put("title").put("date_time"))
            )
        val websiteFunction = JSONObject()
            .put("name", "open_website")
            .put("description", "Open a user-requested public HTTP or HTTPS website.")
            .put(
                "parameters",
                JSONObject()
                    .put("type", "OBJECT")
                    .put(
                        "properties",
                        JSONObject().put("url", JSONObject().put("type", "STRING"))
                    )
                    .put("required", JSONArray().put("url"))
            )
        return JSONObject().put(
            "function_declarations",
            JSONArray().put(appFunction).put(alarmFunction).put(reminderFunction).put(websiteFunction)
        )
    }

    private fun readAction(content: JSONObject): NativeAction? {
        val parts = content.optJSONArray("parts") ?: return null
        for (index in 0 until parts.length()) {
            val functionCall = parts.optJSONObject(index)?.optJSONObject("functionCall") ?: continue
            val name = functionCall.optString("name")
            if (name in setOf("open_android_app", "set_alarm", "create_reminder", "open_website")) {
                return NativeAction(name, functionCall.optJSONObject("args") ?: JSONObject())
            }
        }
        return null
    }

    private fun readText(content: JSONObject, groundingMetadata: JSONObject? = null): String {
        val parts = content.optJSONArray("parts") ?: return "NIANG IA n’a pas renvoyé de texte."
        val text = (0 until parts.length())
            .mapNotNull { parts.optJSONObject(it)?.optString("text") }
            .filter { it.isNotBlank() }
            .joinToString("\n")
        val sources = groundingMetadata?.optJSONArray("groundingChunks")
        val citations = sources?.let { chunks ->
            (0 until chunks.length())
                .mapNotNull { index -> chunks.optJSONObject(index)?.optJSONObject("web") }
                .mapNotNull { web ->
                    val uri = web.optString("uri")
                    if (uri.startsWith("https://") || uri.startsWith("http://")) {
                        "${web.optString("title", uri)}: $uri"
                    } else {
                        null
                    }
                }
                .distinct()
        }.orEmpty()
        val answer = text.ifBlank { "NIANG IA n’a pas renvoyé de texte." }
        return if (citations.isEmpty()) answer else "$answer\n\nSources :\n${citations.joinToString("\n")}"
    }

    private fun copyArray(source: JSONArray): JSONArray = JSONArray(source.toString())
}
