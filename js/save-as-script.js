import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { $el } from "../../scripts/ui.js";

app.registerExtension({
	name: "Comfy.SaveAsScript",
	init() {
		$el("style", {
			parent: document.head,
		});
	},
	async setup() {
		const menu = document.querySelector(".comfy-menu");
		const separator = document.createElement("hr");

		separator.style.margin = "20px 0";
		separator.style.width = "100%";
		menu.append(separator);

		const saveButton = document.createElement("button");
		saveButton.textContent = "Save as Script";
		saveButton.onclick = () => {
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
			}
		menu.append(saveButton);
		
		console.log("SaveAsScript loaded");
	}
});
