import * as http from "node:http";
import * as vscode from "vscode";

let server: http.Server | undefined;

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("lmProxy.start", () => startServer(context)),
    vscode.commands.registerCommand("lmProxy.stop", () => stopServer()),
    vscode.commands.registerCommand("lmProxy.status", () => showStatus())
  );

  const autoStart = vscode.workspace
    .getConfiguration("lmProxy")
    .get<boolean>("autoStart", true);

  if (autoStart) {
    startServer(context);
  }
}

export function deactivate(): void {
  stopServer();
}

function getPort(): number {
  return vscode.workspace.getConfiguration("lmProxy").get<number>("port", 19280);
}

function getModelFamily(): string {
  return vscode.workspace
    .getConfiguration("lmProxy")
    .get<string>("modelFamily", "gpt-4o");
}

async function handleGenerate(
  body: { prompt: string; systemPrompt?: string; timeout?: number },
  req: http.IncomingMessage,
  res: http.ServerResponse
): Promise<void> {
  const family = getModelFamily();

  const models = await vscode.lm.selectChatModels({ family });
  if (models.length === 0) {
    sendJson(res, 503, {
      error: `No language model available for family '${family}'`,
    });
    return;
  }

  const model = models[0];
  const messages: vscode.LanguageModelChatMessage[] = [];

  if (body.systemPrompt) {
    messages.push(vscode.LanguageModelChatMessage.User(body.systemPrompt));
  }
  messages.push(vscode.LanguageModelChatMessage.User(body.prompt));

  const cts = new vscode.CancellationTokenSource();

  // Cancel the LM request if the client disconnects
  req.on("close", () => cts.cancel());

  // Cancel the LM request after the specified timeout (default: no timeout)
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeoutSec = typeof body.timeout === "number" && body.timeout > 0 ? body.timeout : 0;
  if (timeoutSec > 0) {
    timer = setTimeout(() => cts.cancel(), timeoutSec * 1000);
  }

  try {
    const response = await model.sendRequest(messages, {}, cts.token);

    let content = "";
    for await (const chunk of response.text) {
      content += chunk;
    }

    sendJson(res, 200, {
      content: content.trim(),
      model: model.id,
      family: model.family,
    });
  } catch (err: unknown) {
    if (cts.token.isCancellationRequested) {
      sendJson(res, 504, { error: "LM request cancelled (timeout or client disconnect)" });
    } else {
      const message = err instanceof Error ? err.message : String(err);
      sendJson(res, 500, { error: message });
    }
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
    cts.dispose();
  }
}

function startServer(context: vscode.ExtensionContext): void {
  if (server) {
    vscode.window.showInformationMessage(
      `LM Proxy already running on port ${getPort()}`
    );
    return;
  }

  const port = getPort();

  server = http.createServer((req, res) => {
    // CORS headers for local use
    res.setHeader("Access-Control-Allow-Origin", "127.0.0.1");
    res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");

    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }

    if (req.method === "GET" && req.url === "/health") {
      sendJson(res, 200, { status: "ok", model_family: getModelFamily() });
      return;
    }

    if (req.method === "POST" && req.url === "/generate") {
      let rawBody = "";
      req.on("data", (chunk: Buffer) => {
        rawBody += chunk.toString();
        // Guard against oversized payloads (1MB)
        if (rawBody.length > 1_048_576) {
          sendJson(res, 413, { error: "Payload too large" });
          req.destroy();
        }
      });
      req.on("end", () => {
        try {
          const body = JSON.parse(rawBody);
          if (!body.prompt || typeof body.prompt !== "string") {
            sendJson(res, 400, {
              error: "Missing required field: prompt (string)",
            });
            return;
          }
          handleGenerate(body, req, res).catch((err: unknown) => {
            const message = err instanceof Error ? err.message : String(err);
            sendJson(res, 500, { error: message });
          });
        } catch {
          sendJson(res, 400, { error: "Invalid JSON body" });
        }
      });
      return;
    }

    sendJson(res, 404, { error: "Not found. Use POST /generate or GET /health" });
  });

  server.listen(port, "127.0.0.1", () => {
    const msg = `LM Proxy server started on http://127.0.0.1:${port}`;
    vscode.window.showInformationMessage(msg);
    console.log(msg);
  });

  server.on("error", (err: Error) => {
    vscode.window.showErrorMessage(`LM Proxy server error: ${err.message}`);
    server = undefined;
  });
}

function stopServer(): void {
  if (server) {
    server.close();
    server = undefined;
    vscode.window.showInformationMessage("LM Proxy server stopped");
  } else {
    vscode.window.showInformationMessage("LM Proxy server is not running");
  }
}

function showStatus(): void {
  if (server) {
    vscode.window.showInformationMessage(
      `LM Proxy running on http://127.0.0.1:${getPort()} (model family: ${getModelFamily()})`
    );
  } else {
    vscode.window.showInformationMessage("LM Proxy server is not running");
  }
}

function sendJson(
  res: http.ServerResponse,
  status: number,
  data: Record<string, unknown>
): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}
