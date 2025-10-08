import time
import socketio

# Connect to Node.js WebSocket server (acting as Socket.IO server here)
sio = socketio.Client()

@sio.event
def connect():
    print("✅ Connected to Node.js WebSocket server")

@sio.event
def disconnect():
    print("❌ Disconnected")

sio.connect("http://localhost:4000")  # Node.js server URL

def long_running_task():
    for i in range(5):
        time.sleep(2)  # simulate work
        sio.emit("progress", {"step": i+1, "status": f"Step {i+1} complete"})
    
    sio.emit("done", {"result": "✅ All steps finished!"})

if __name__ == "__main__":
    long_running_task()
    sio.disconnect()
