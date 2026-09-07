/* WebSocket 客户端。
 *
 * 职责：
 *   1. 接收后端实时测试进度；
 *   2. 应答后端心跳（2 秒一次，连续 3 次无应答后端自动终止测试）；
 *   3. 断线自动重连。
 *
 * 心跳策略：
 *   收到 {type:'ping'} 立即回 {type:'pong'}；
 *   同时每 5 秒主动发一次 heartbeat，防止后端判定失联。
 */
(function (global) {
  'use strict';

  var RECONNECT_INTERVAL = 3000;
  var ACTIVE_HEARTBEAT_INTERVAL = 5000;

  function WsClient() {
    this.socket = null;
    this.handlers = {};
    this.activeTimer = null;
    this.reconnectTimer = null;
    this.closedByUser = false;
  }

  WsClient.prototype.connect = function () {
    var self = this;
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return;
    }
    var protocol = location.protocol === 'https:' ? 'wss://' : 'ws://';
    var url = protocol + location.host + '/ws';
    this.closedByUser = false;
    try {
      this.socket = new WebSocket(url);
    } catch (error) {
      this._scheduleReconnect();
      return;
    }
    this.socket.onmessage = function (event) {
      self._onMessage(event.data);
    };
    this.socket.onclose = function () {
      if (!self.closedByUser) {
        self._scheduleReconnect();
      }
    };
    this.socket.onerror = function () {
      /* 错误交由 onclose 统一处理 */
    };
    this._startActiveHeartbeat();
  };

  WsClient.prototype._scheduleReconnect = function () {
    var self = this;
    if (this.reconnectTimer) {
      return;
    }
    this.reconnectTimer = setTimeout(function () {
      self.reconnectTimer = null;
      self.connect();
    }, RECONNECT_INTERVAL);
  };

  WsClient.prototype._startActiveHeartbeat = function () {
    var self = this;
    if (this.activeTimer) {
      clearInterval(this.activeTimer);
    }
    this.activeTimer = setInterval(function () {
      self.send({ type: 'heartbeat' });
    }, ACTIVE_HEARTBEAT_INTERVAL);
  };

  WsClient.prototype._onMessage = function (text) {
    var payload;
    try {
      payload = JSON.parse(text);
    } catch (error) {
      return;
    }
    if (!payload || typeof payload !== 'object') {
      return;
    }
    if (payload.type === 'ping') {
      this.send({ type: 'pong' });
      return;
    }
    var handlers = this.handlers[payload.type] || [];
    handlers.forEach(function (handler) {
      try {
        handler(payload.data || {}, payload);
      } catch (error) {
        if (global.RtDebug) {
          global.RtDebug.error('ws_handler_error', { message: String(error) });
        }
      }
    });
  };

  WsClient.prototype.send = function (payload) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  };

  WsClient.prototype.on = function (type, handler) {
    if (!this.handlers[type]) {
      this.handlers[type] = [];
    }
    this.handlers[type].push(handler);
  };

  WsClient.prototype.off = function (type, handler) {
    if (!this.handlers[type]) {
      return;
    }
    this.handlers[type] = this.handlers[type].filter(function (item) {
      return item !== handler;
    });
  };

  WsClient.prototype.close = function () {
    this.closedByUser = true;
    if (this.activeTimer) {
      clearInterval(this.activeTimer);
      this.activeTimer = null;
    }
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  };

  global.RtWs = new WsClient();
})(window);
