import json
import tkinter as tk
from pathlib import Path


mode = json.loads(Path("scenario.json").read_text(encoding="utf-8"))["mode"]
root = tk.Tk()
root.title(f"NIANG Desktop Fixture {mode}")
root.geometry("600x400+40+40")
root.configure(bg="white")
root.option_add("*Font", "Arial 16")


if mode == "button":
    count = tk.IntVar(value=0)

    def increment():
        count.set(count.get() + 1)
        status.configure(text=f"Count: {count.get()}")

    status = tk.Label(root, text="Count: 0", name="status")
    status.pack(pady=8)
    tk.Button(root, text="Increment", command=increment).pack(pady=20)
elif mode == "form":
    tk.Label(root, text="Project name").place(x=32, y=38)
    entry = tk.Entry(root, name="project_name", width=28)
    entry.place(x=32, y=86, width=420, height=38)
    status = tk.Label(root, text="Not saved", name="save_status")
    status.place(x=32, y=150)
    tk.Button(
        root,
        text="Save project",
        command=lambda: status.configure(text=f"Saved: {entry.get()}"),
    ).place(x=32, y=205)
elif mode == "multi":
    tk.Label(root, text="Primary window").pack(pady=20)
    secondary = tk.Toplevel(root)
    secondary.transient(root)
    secondary.title("NIANG Desktop Fixture Secondary")
    secondary.geometry("360x180+700+100")
    tk.Label(secondary, text="Secondary window").pack(pady=24)
elif mode == "dialog":
    dialog = tk.Toplevel(root)
    dialog.transient(root)
    dialog.title("NIANG Desktop Fixture Dialog")
    dialog.geometry("360x180+700+100")
    tk.Label(dialog, text="Dialog ready").pack(pady=24)
    tk.Button(dialog, text="Close dialog", command=dialog.destroy).pack()
elif mode == "minimized":
    tk.Label(root, text="Minimize state test").pack(pady=32)
    root.after(800, root.iconify)
elif mode == "error":
    root.title("NIANG Desktop Fixture Error")
    root.after(500, root.destroy)
    root.mainloop()
    print("intentional fixture stdout", flush=True)
    raise RuntimeError("INTENTIONAL_FIXTURE_ERROR")
else:
    raise ValueError(f"Unknown fixture scenario: {mode}")

root.mainloop()
