/* WebSocket 客户端。
 *
 * 职责：
 *   1. 接收后端实时测试进度；
 *   2. 应答后端 ping，维持连接可推送；
 *   3. 断线自动重连。
 *
 * 范围界定（需求5）：
 *   本连接**不参与测试存活判定**。测试是否继续，唯一判据是
 *   「当前页面是否仍是测试页面」，由 app.js 的页面级心跳负责：
 *   测试页面每 2 秒上报一次，离开测试页面立即通知后端中断测试。
 *   因此这里断线或未应答都不会停止测试（否则切后台、刷新页面会误伤），
 *   只是该连接暂时收不到实时推送，重连后恢复。
 *
 * 心跳策略：
 *   收到 {type:'ping'} 立即回 {type:'pong'}；
 *   同时每 5 秒主动发一次 heartbeat，维持连接活跃。
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
