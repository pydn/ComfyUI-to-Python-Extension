import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";

const DEFAULT_SCRIPT_FILENAME = "workflow_api.py";
const DEFAULT_WORKFLOW_NAME = "workflow_api.json";

function $el(tag, options = {}) {
	const element = document.createElement(tag);
	const { parent, style, ...props } = options;

	if (style) {
		Object.assign(element.style, style);
	}

	Object.assign(element, props);

	if (parent) {
		parent.appendChild(element);
	}

	return element;
}

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
		const filename = DEFAULT_SCRIPT_FILENAME;

		app.graphToPrompt().then(async (p) => {
			const frontendWorkflow = p.workflow ?? app.graph.serialize();
			const json = JSON.stringify({
				name: DEFAULT_WORKFLOW_NAME,
				workflow: JSON.stringify(p.output, null, 2),
				frontend_workflow: JSON.stringify(frontendWorkflow, null, 2),
			}, null, 2); // convert the data to a JSON string
			var response = await api.fetchApi(`/saveasscript`, { method: "POST", body: json });
			if(response.status == 200) {
				const blob = new Blob([await response.text()], {type: "text/python;charset=utf-8"});
				const url = URL.createObjectURL(blob);
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
