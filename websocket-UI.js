import React, { useEffect, useState } from "react";
import io from "socket.io-client";

const socket = io("http://localhost:4000"); // Node.js WS server

export default function App() {
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    socket.on("progress", (msg) => {
      setMessages((prev) => [...prev, `Progress: ${msg.status}`]);
    });

    socket.on("done", (msg) => {
      setMessages((prev) => [...prev, `Done: ${msg.result}`]);
    });

    return () => {
      socket.off("progress");
      socket.off("done");
    };
  }, []);

  return (
    <div>
      <h1>Live Job Status</h1>
      <ul>
        {messages.map((m, i) => (
          <li key={i}>{m}</li>
        ))}
      </ul>
    </div>
  );
}
