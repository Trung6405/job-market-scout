import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import logger from './logger.js';

/**
 * Manages SSE server transports for multiple client connections.
 *
 * Each connection gets its own McpServer instance (see index.js), so this
 * tracks the transport and its owning server together, keyed by sessionId,
 * instead of assuming one shared server for every session.
 */
class SseManager {
  /**
   * @type {Object.<string, {transport: SSEServerTransport, server: import('@modelcontextprotocol/sdk/server/mcp.js').McpServer}>}
   */
  transports = {};

  /**
   * Storage for progress tokens by sessionId
   */
  progressTokens = {};

  /**
   * Storage for tool calls by connectionId and toolCallId
   */
  toolCalls = {};

  /**
   * Adds a new SSE transport for a client
   * @param {string} sendPath - Path for client to send messages to
   * @param {Response} res - Express response object
   * @param {import('@modelcontextprotocol/sdk/server/mcp.js').McpServer} server - The server instance owning this connection
   * @returns {SSEServerTransport} The created transport
   */
  createTransport(sendPath, res, server) {
    const transport = new SSEServerTransport(sendPath, res);
    this.transports[transport.sessionId] = { transport, server };
    return transport;
  }

  /**
   * Gets a transport by sessionId
   * @param {Request} req - Express request object
   * @returns {SSEServerTransport|undefined} The transport or undefined if not found
   */
  getTransport(req) {
    const sessionId = req.query.sessionId;
    this.progressTokens[sessionId] = req.body?.params?._meta?.progressToken;
    return this.transports[sessionId]?.transport;
  }

  /**
   * Removes a transport when client disconnects
   * @param {string} sessionId - Session ID to remove
   */
  removeTransport(sessionId) {
    if (this.transports[sessionId]) {
      delete this.transports[sessionId];
      delete this.progressTokens[sessionId];
      logger.info(`Removed transport for session: ${sessionId}`);
      return true;
    }
    return false;
  }

  /**
   * Sends an update to the client for a given session, via that session's
   * own server instance.
   * @param {object} message - Message to broadcast
   * @param {string} sessionId - Session ID to notify
   */
  async notificationProgress(message, sessionId) {
    const entry = this.transports[sessionId];
    if (!entry) {return;}
    await entry.server.server.notification({
      method: 'notifications/progress',
      params: {
        ...message,
        progressToken: this.progressTokens[sessionId],
      },
    });
  }

  /**
   * Checks if there are any active connections
   * @param {string} sessionId
   * @returns {boolean} True if there are active connections
   */
  hasConnection(sessionId) {
    return !!this.transports[sessionId];
  }

  /**
   * Process a stream event from a model
   * @param {Object} event - The event to process
   * @param {string} connectionId - The connection ID
   * @param {string} toolCallId - The tool call ID
   */
  handleStreamEvent(event, connectionId, toolCallId) {
    if (!event || !event.choices || !event.choices[0]) {
      return;
    }

    const delta = event.choices[0].delta;
    if (delta && delta.tool_calls && delta.tool_calls[0]) {
      const toolCall = delta.tool_calls[0];

      // Store or update the tool call in our cache
      if (!this.toolCalls[connectionId]) {
        this.toolCalls[connectionId] = {};
      }

      if (!this.toolCalls[connectionId][toolCallId]) {
        this.toolCalls[connectionId][toolCallId] = {
          function: {
            name: '',
            arguments: '',
          },
          index: toolCall.index,
          id: toolCallId,
        };
      }

      const currentToolCall = this.toolCalls[connectionId][toolCallId];

      if (toolCall.function) {
        if (toolCall.function.name) {
          currentToolCall.function.name = toolCall.function.name;
        }

        if (toolCall.function.arguments) {
          currentToolCall.function.arguments += toolCall.function.arguments;
        }
      }
    }
  }
}

export default SseManager;
