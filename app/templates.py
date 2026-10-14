TEMPLATES = {
    "linux": {
        "id": "linux",
        "name": "Linux Basics",
        "tag": "FOUNDATIONS",
        "icon": ">_",
        "description": "Get comfortable with the shell. Explore files, pipes, permissions, and processes.",
        "language": "Bash",
        "entry": "hello.sh",
        "run": "bash hello.sh",
        "cpu": 0.5,
        "memory_mb": 256,
        "tasks": [
            "Run pwd and ls -la to explore your workspace.",
            "Create a notes directory and a file inside it.",
            "Use a pipe to count the files in /usr/bin.",
            "Edit hello.sh, save it, and run your script.",
        ],
        "files": {
            "hello.sh": '#!/bin/bash\necho "Welcome to your Linux lab!"\necho "Current directory: $PWD"\necho "Files in this workspace:"\nls -la\n',
            "notes/welcome.txt": "Your files in /workspace survive stop and resume.\nTry: cat notes/welcome.txt\n",
        },
    },
    "python": {
        "id": "python",
        "name": "Python Lab",
        "tag": "BUILD & EXPERIMENT",
        "icon": "Py",
        "description": "Turn an idea into working code. Practice Python with a ready-to-run starter exercise.",
        "language": "Python 3.12",
        "entry": "main.py",
        "run": "python main.py",
        "cpu": 1.0,
        "memory_mb": 512,
        "tasks": [
            "Run main.py and inspect the output.",
            "Add another student and score to the dictionary.",
            "Write a function that returns the highest score.",
            "Save your work and create a backup after stopping the lab.",
        ],
        "files": {
            "main.py": '"""CloudLab starter: calculate a class average."""\n\nscores = {"Asha": 92, "Ravi": 85, "Maya": 96}\n\ndef average(values):\n    return sum(values) / len(values)\n\nfor student, score in scores.items():\n    print(f"{student}: {score}")\nprint(f"Class average: {average(list(scores.values())):.1f}")\n',
            "README.md": "# Python workspace\n\nRun `python main.py`. Add your own Python files here.\n",
        },
    },
    "web": {
        "id": "web",
        "name": "Web Development",
        "tag": "MAKE SOMETHING",
        "icon": "</>",
        "description": "Build for the browser with HTML, CSS, and JavaScript. Node.js is ready when you are.",
        "language": "Node.js 22",
        "entry": "index.html",
        "run": "node main.js",
        "cpu": 1.0,
        "memory_mb": 512,
        "tasks": [
            "Open index.html in the editor and change the heading.",
            "Open Preview to see your page in a sandbox.",
            "Change the colors in style.css and preview again.",
            "Run main.js with Node.js from the terminal.",
        ],
        "files": {
            "index.html": '<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8"><title>My first CloudLab page</title><link rel="stylesheet" href="style.css"></head>\n<body><main><span>BUILT IN CLOUDLAB</span><h1>Hello, world.</h1><p>Your next idea starts here.</p><button id="hello">Say hello</button></main><script src="script.js"></script></body>\n</html>\n',
            "style.css": "body { margin: 0; background: #edf3ed; color: #18392e; font: 18px system-ui; }\nmain { max-width: 640px; margin: 12vh auto; padding: 32px; }\nspan { font-size: 12px; letter-spacing: 3px; }\nh1 { font-size: 72px; letter-spacing: -4px; }\nbutton { border: 0; border-radius: 30px; padding: 14px 24px; background: #18392e; color: white; cursor: pointer; }\n",
            "script.js": 'document.getElementById("hello").addEventListener("click", () => {\n  document.querySelector("p").textContent = "You just made your page interactive!";\n});\n',
            "main.js": 'const message = "Hello from your isolated Node.js workspace!";\nconsole.log(message);\nconsole.log(`Node version: ${process.version}`);\n',
        },
    },
}


def list_templates():
    return [
        {key: value for key, value in template.items() if key != "files"} for template in TEMPLATES.values()
    ]
