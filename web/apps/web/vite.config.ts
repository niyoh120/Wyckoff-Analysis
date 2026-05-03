import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import type { Plugin } from 'vite'

function llmProxyPlugin(): Plugin {
  return {
    name: 'llm-proxy',
    configureServer(server) {
      server.middlewares.use('/api/llm-proxy', async (req, res) => {
        const targetUrl = req.headers['x-target-url'] as string
        if (!targetUrl) {
          res.statusCode = 400
          res.end(JSON.stringify({ error: 'Missing X-Target-URL header' }))
          return
        }

        const url = targetUrl + (req.url || '')
        const headers: Record<string, string> = {}
        for (const [key, value] of Object.entries(req.headers)) {
          if (key === 'host' || key === 'x-target-url' || key === 'connection') continue
          if (value) headers[key] = Array.isArray(value) ? value[0]! : value
        }

        try {
          const chunks: Buffer[] = []
          await new Promise<void>((resolve) => {
            req.on('data', (chunk) => { chunks.push(Buffer.from(chunk)) })
            req.on('end', () => resolve())
          })
          const body = Buffer.concat(chunks)

          const fetchHeaders: Record<string, string> = {}
          for (const [key, value] of Object.entries(headers)) {
            if (key === 'content-length' || key === 'user-agent') continue
            fetchHeaders[key] = value
          }
          fetchHeaders['content-length'] = String(body.length)
          fetchHeaders['user-agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

          console.log(`[llm-proxy] ${req.method} ${url}`)

          const response = await fetch(url, {
            method: req.method || 'POST',
            headers: fetchHeaders,
            body: body.length > 0 ? body : undefined,
          })

          res.statusCode = response.status
          for (const [key, value] of response.headers.entries()) {
            if (key === 'transfer-encoding' || key === 'content-encoding') continue
            res.setHeader(key, value)
          }

          const responseBody = await response.arrayBuffer()
          res.end(Buffer.from(responseBody))
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err)
          console.error(`[llm-proxy] ERROR: ${msg}`)
          res.statusCode = 502
          res.end(JSON.stringify({ error: { message: `Proxy error → ${url}: ${msg}` } }))
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), llmProxyPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
  },
})
