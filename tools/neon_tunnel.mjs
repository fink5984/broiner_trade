// Local TCP -> Neon WebSocket tunnel (for networks that block raw Postgres port 5432 but allow HTTPS/WSS).
// Usage: node tools/neon_tunnel.mjs <neon-host> [localPort=54329]
// Then use DATABASE_URL=postgresql+psycopg://USER:PASS@127.0.0.1:54329/DB?sslmode=disable
// TLS is provided by the wss:// leg, so the local leg is plain and bound to 127.0.0.1 only.
import net from 'node:net'

const host = process.argv[2]
const port = Number(process.argv[3] ?? 54329)
if (!host) { console.error('usage: node neon_tunnel.mjs <neon-host> [port]'); process.exit(1) }

net.createServer((sock) => {
  const ws = new WebSocket(`wss://${host}/v2`)
  ws.binaryType = 'arraybuffer'
  const queue = []
  let open = false
  ws.onopen = () => { open = true; queue.forEach((b) => ws.send(b)); queue.length = 0 }
  ws.onmessage = (e) => sock.write(Buffer.from(e.data))
  ws.onclose = () => sock.destroy()
  ws.onerror = (e) => { console.error('ws error', e.message ?? ''); sock.destroy() }
  sock.on('data', (b) => (open ? ws.send(b) : queue.push(b)))
  sock.on('close', () => { try { ws.close() } catch { /* ignore */ } })
  sock.on('error', () => { try { ws.close() } catch { /* ignore */ } })
}).listen(port, '127.0.0.1', () => console.log(`neon tunnel ${host} -> 127.0.0.1:${port}`))
