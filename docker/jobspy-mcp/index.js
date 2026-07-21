import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import express from 'express';
import cors from 'cors';
import logger from './logger.js';
import SseManager from './sseManager.js';
import { searchJobsTool, searchJobsHandler } from './tools/index.js';

// Environment configuration
const PORT = process.env.JOBSPY_PORT || 9423;
const HOST = process.env.JOBSPY_HOST || '0.0.0.0';
const ENABLE_SSE = !!(process.env.ENABLE_SSE | 0);

// One SseManager is shared across every connection: it just tracks
// transports/servers by sessionId, it holds no per-connection MCP state.
const sseManager = new SseManager();

// Upstream's prompt registrations (searchJobsPrompt, jobRecommendationsPrompt,
// resumeFeedbackPrompt) pass z.object(...) where the MCP SDK expects a raw
// Zod shape, crashing the server before it can bind its port. We only need
// the search_jobs tool, so they're intentionally not registered here.
function createServer() {
  const server = new McpServer({
    name: 'JobSpy MCP Server',
    version: '1.0.0',
    description:
      'A Model Context Protocol server that enables searching for jobs across various platforms',
  });
  searchJobsTool(server, sseManager);
  return server;
}

// Initialize transports
let stdioTransport = null;
let httpServer = null;

// Start the server with configured transports
async function runServer() {
  logger.info('Starting JobSpy MCP server...');

  try {
    // Initialize and connect transports
    const connectedTransports = [];

    // Set up SSE transport if enabled
    if (ENABLE_SSE) {
      try {
        // Create Express app
        const app = express();

        // Configure CORS
        app.use(cors());

        // Configure Express middleware
        app.use(express.json());
        app.use(express.urlencoded({ extended: true }));

        // Health check endpoint
        app.get('/health', (req, res) => {
          res.status(200).json({ status: 'ok' });
        });

        // SSE endpoint for client connections. Each client gets its own
        // McpServer instance so concurrent connections no longer stomp on
        // each other's transport (the MCP SDK's Server supports only one
        // active transport at a time).
        app.get('/sse', async (req, res) => {
          const server = createServer();
          const transport = sseManager.createTransport('/messages', res, server);

          res.on('close', () => {
            sseManager.removeTransport(transport.sessionId);
            logger.info(`Client disconnected: ${transport.sessionId}`);
          });

          await server.connect(transport);
          logger.info(`New SSE client connected: ${transport.sessionId}`);
        });

        // Message handling endpoint
        app.post('/messages', async (req, res) => {
          const transport = sseManager.getTransport(req);

          if (transport) {
            await transport.handlePostMessage(req, res, req.body);
          } else {
            res.status(400).send('No transport found for sessionId');
          }
        });

        app.post('/api', async (req, res) => {
          const data = await searchJobsHandler(req.body);
          res.json(data);
        });

        // Start the Express server
        httpServer = app.listen(PORT, HOST, () => {
          logger.info(`SSE server listening at http://${HOST}:${PORT}`);
        });

        connectedTransports.push('SSE');

        logger.info(`SSE transport listening at http://${HOST}:${PORT}/sse`);
        logger.info(
          `Send endpoint available at http://${HOST}:${PORT}/messages`,
        );
      } catch (error) {
        logger.error('Failed to connect SSE transport', {
          error: error.message,
          stack: error.stack,
        });
      }
    } else {
      // Set up stdio transport if no SSE
      try {
        const server = createServer();
        stdioTransport = new StdioServerTransport();
        await server.connect(stdioTransport);
        connectedTransports.push('stdio');

        logger.info('Stdio transport connected');
      } catch (error) {
        logger.error('Failed to connect stdio transport', {
          error: error.message,
        });
      }
    }

    // Ensure at least one transport is connected
    if (connectedTransports.length === 0) {
      throw new Error('No transports connected. Check configuration.');
    }

    logger.info(
      `Server successfully connected with transports: ${connectedTransports.join(
        ', ',
      )}`,
    );
  } catch (error) {
    logger.error('Server connection error', {
      error: error.message,
      stack: error.stack,
    });
    process.exit(1);
  }
}

// Handle graceful shutdown
async function shutdown() {
  logger.info('Shutting down JobSpy MCP server...');

  try {
    // Close HTTP server if it exists
    if (httpServer) {
      httpServer.close(() => {
        logger.info('HTTP server closed');
      });
    }

    logger.info('Server shutdown complete');
  } catch (error) {
    logger.error('Error during shutdown', { error: error.message });
  } finally {
    // Give logger time to flush
    setTimeout(() => process.exit(0), 100);
  }
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

// Run the server
runServer().catch((error) => {
  logger.error('Unhandled error in server', { error: error.message });
  process.exit(1);
});
