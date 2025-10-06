// server.js
const WebSocket = require("ws");
const axios = require("axios");

const wss = new WebSocket.Server({ port: 8080 });

wss.on("connection", (ws) => {
  console.log("Client connected");

  ws.on("message", async (message) => {
    const data = JSON.parse(message);

    if (data.type === "start_job") {
      // 1. Immediately notify client
      ws.send(JSON.stringify({ status: "started", jobId: data.jobId }));

      try {
        // 2. Call Python API (long running)
        const response = await axios.post("http://localhost:5000/your-python-endpoint", {
          jobId: data.jobId,
          params: data.params
        });

        // 3. Once done, send final result
        ws.send(JSON.stringify({ status: "completed", jobId: data.jobId, result: response.data }));
      } catch (err) {
        ws.send(JSON.stringify({ status: "error", jobId: data.jobId, error: err.message }));
      }
    }
  });

  ws.on("close", () => {
    console.log("Client disconnected");
  });
});
