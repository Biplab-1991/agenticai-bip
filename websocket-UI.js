import React, { useEffect, useState } from "react";

function JobRunner() {
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8080");

    ws.onopen = () => {
      console.log("Connected to WebSocket server");
      // Start the job immediately (you can trigger this via button click instead)
      ws.send(JSON.stringify({ type: "start_job", jobId: "1234", params: { foo: "bar" } }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      setMessages((prev) => [...prev, msg]);
    };

    ws.onclose = () => console.log("Disconnected from WebSocket server");

    return () => ws.close();
  }, []);

  return (
    <div>
      <h2>Job Status</h2>
      <ul>
        {messages.map((m, i) => (
          <li key={i}>
            {m.status === "started" && <>🚀 Job {m.jobId} started</>}
            {m.status === "completed" && <>✅ Result: {JSON.stringify(m.result)}</>}
            {m.status === "error" && <>❌ Error: {m.error}</>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default JobRunner;
