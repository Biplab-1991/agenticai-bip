// install: npm install express socket.io
const express = require("express");
const { createServer } = require("http");
const { Server } = require("socket.io");

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
  cors: { origin: "*" }, // allow React UI
});

io.on("connection", (socket) => {
  console.log("⚡ Client connected:", socket.id);

  // Forward any Python messages to all UI clients
  socket.on("progress", (msg) => {
    console.log("Progress from Python:", msg);
    io.emit("progress", msg); // broadcast to React
  });

  socket.on("done", (msg) => {
    console.log("Done from Python:", msg);
    io.emit("done", msg); // broadcast to React
  });

  socket.on("disconnect", () => {
    console.log("Client disconnected");
  });
});

httpServer.listen(4000, () => {
  console.log("🚀 WebSocket server running on http://localhost:4000");
});
