import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";

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
		const style = document.createElement("style");
		document.head.appendChild(style);
	},
	async getPromptPayload() {
		const graphToPrompt = app.graphToPrompt?.bind(app);
		if (!graphToPrompt) {
			throw new Error("ComfyUI graph export API is unavailable.");
		}

		const attempts = [
			() => graphToPrompt(),
			() => graphToPrompt(app.graph),
			() => graphToPrompt(app.graph, {}),
		];

		let lastError = null;
		for (const attempt of attempts) {
			try {
				const result = await attempt();
				const workflow = result?.output ?? result?.prompt ?? result?.workflow ?? result;
				if (workflow && typeof workflow === "object") {
					return workflow;
				}
			} catch (error) {
				lastError = error;
			}
		}

		throw lastError || new Error("Unable to export the current workflow from ComfyUI.");
	},
	async postSaveAsScript(body) {
		const endpoints = ["/api/saveasscript", "/saveasscript"];
		let lastResponse = null;

		for (const endpoint of endpoints) {
			const response = await api.fetchApi(endpoint, { method: "POST", body });
			if (response.status !== 404) {
				return response;
			}
			lastResponse = response;
		}

		return lastResponse;
	},
	createDownloadLink(url, filename) {
		const anchor = document.createElement("a");
		anchor.href = url;
		anchor.download = filename;
		anchor.style.display = "none";
		document.body.appendChild(anchor);
		return anchor;
	},
	async savePythonScript() {
		var filename = prompt("Save script as:");
		if(filename === undefined || filename === null || filename === "") {
			return
		}

		try {
			const workflow = await extension.getPromptPayload();
			const json = JSON.stringify({name: filename + ".json", workflow: JSON.stringify(workflow, null, 2)}, null, 2);
			var response = await extension.postSaveAsScript(json);
			if(response.status == 200) {
				const blob = new Blob([await response.text()], {type: "text/python;charset=utf-8"});
				const url = URL.createObjectURL(blob);
				if(!filename.endsWith(".py")) {
					filename += ".py";
				}

				const a = extension.createDownloadLink(url, filename);
				a.click();
				setTimeout(function () {
					a.remove();
					window.URL.revokeObjectURL(url);
				}, 0);
				return;
			}
			let message = `Export failed with status ${response.status}.`;
			try {
				const payload = await response.json();
				message = payload.error || message;
				if (payload.class_type || payload.node_id || payload.stage) {
					const details = [
						payload.class_type ? `node class: ${payload.class_type}` : null,
						payload.node_id ? `node id: ${payload.node_id}` : null,
						payload.stage ? `stage: ${payload.stage}` : null,
					].filter(Boolean);
					if (details.length) {
						message += `\n${details.join("\n")}`;
					}
				}
			} catch (_error) {
				const text = await response.text();
				if (text) {
					message = text;
				}
			}
			window.alert(message);
		} catch (error) {
			window.alert(error?.message || "Unable to export the current workflow.");
		}
	},
	async setup() {
		console.log("SaveAsScript loaded");
	}
};

app.registerExtension(extension);
