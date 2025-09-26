import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { $el } from "../../scripts/ui.js";

const extension = {
	name: "Comfy.SaveAsScript",
	commands: [
				{
					id: "triggerSaveAsScript",
					label: "Save As Script",
					function: () => { extension.savePythonScript(); }
				}
			],
	menuCommands: [
		{
			path: ["File"],
			commands: ["triggerSaveAsScript"]
		}
	],
	init() {
		$el("style", {
			parent: document.head,
		});
	},
	savePythonScript() {
		var filename = prompt("Save script as:");
		if(filename === undefined || filename === null || filename === "") {
			return
		}
		
		app.graphToPrompt().then(async (p) => {
			const json = JSON.stringify({name: filename + ".json", workflow: JSON.stringify(p.output, null, 2)}, null, 2); // convert the data to a JSON string
			var response = await api.fetchApi(`/saveasscript`, { method: "POST", body: json });
			if(response.status == 200) {
				const blob = new Blob([await response.text()], {type: "text/python;charset=utf-8"});
				const url = URL.createObjectURL(blob);
				if(!filename.endsWith(".py")) {
					filename += ".py";
				}

				const a = $el("a", {
					href: url,
					download: filename,
					style: {display: "none"},
					parent: document.body,
				});
				a.click();
				setTimeout(function () {
					a.remove();
					window.URL.revokeObjectURL(url);
				}, 0);
			}
		});
	},
	async setup() {
		console.log("SaveAsScript loaded");
	}
};

app.registerExtension(extension);
