/* 前端 Debug 日志模块。
 *
 * 规范（项目书 22.3）：
 *   1. 使用 ; 分隔字段，并以 ; 结尾；
 *   2. 不依赖额外空格表达信息边界；
 *   3. 时间必须与后端程序日志统一（本地时间 + 时区偏移）；
 *   4. 仅在后端日志等级为 DEBUG 时输出。
 *
 * 示例：
 *   2026-08-29 00:00:01.123+08:00;module=web;event=click;class=test-start-button;position=123,456;js_version=xxx;software_version=xxx;
 */
(function (global) {
  'use strict';

  // 全程序使用同一个版本号：注入前为占位值，启动后由 systemInfo 覆盖
  var JS_VERSION = '20260910-V1';
  var SOFTWARE_VERSION = '20260910-V1';
  var enabled = false;
  var currentPage = 'home';

  function pad(value, length) {
    var text = String(value);
    while (text.length < length) {
      text = '0' + text;
    }
    return text;
  }

  /* 生成与后端一致的时间戳：YYYY-MM-DD HH:MM:SS.mmm+08:00 */
  function timestamp() {
    var now = new Date();
    var base = now.getFullYear() + '-' + pad(now.getMonth() + 1, 2) + '-' + pad(now.getDate(), 2);
    var clock = pad(now.getHours(), 2) + ':' + pad(now.getMinutes(), 2) + ':' + pad(now.getSeconds(), 2);
    var millis = pad(now.getMilliseconds(), 3);
    var offsetMinutes = -now.getTimezoneOffset();
    var sign = offsetMinutes >= 0 ? '+' : '-';
    var abs = Math.abs(offsetMinutes);
    var zone = sign + pad(Math.floor(abs / 60), 2) + ':' + pad(abs % 60, 2);
    return base + ' ' + clock + '.' + millis + zone;
  }

  function emit(event, fields) {
    if (!enabled) {
      return;
    }
    var parts = ['time=' + timestamp(), 'module=web', 'event=' + (event || 'unknown')];
    parts.push('page=' + (currentPage || 'unknown'));
    if (fields) {
      Object.keys(fields).forEach(function (key) {
        var value = fields[key];
        if (value === null || value === undefined) {
          value = '';
        }
        parts.push(key + '=' + String(value).replace(/[;\r\n]/g, ' '));
      });
    }
    parts.push('js_version=' + JS_VERSION);
    parts.push('software_version=' + SOFTWARE_VERSION);
    var line = parts.join(';') + ';';
    // 使用 console.log 而非 console.debug：后者在 Chrome 默认 Info 级别下被过滤，
    // 开启 DEBUG 后前端 Debug 信息不可见。
    if (global.console && global.console.log) {
      global.console.log(line);
    }
  }

  var DebugLogger = {
    setEnabled: function (value) {
      enabled = !!value;
    },
    isEnabled: function () {
      return enabled;
    },
    setPage: function (page) {
      currentPage = page || 'unknown';
    },
    setSoftwareVersion: function (value) {
      if (value) {
        SOFTWARE_VERSION = value;
        JS_VERSION = value;
      }
    },
    /* 注入版本号（前后端同一版本号，来自后端 systemInfo.software_version） */
    setJsVersion: function (value) {
      if (value) {
        JS_VERSION = value;
        SOFTWARE_VERSION = value;
      }
    },
    /* 记录用户点击：包含点击时间、点击位置、HTML class、操作结果 */
    click: function (element, event, extra) {
      var classText = '';
      var tag = '';
      if (element) {
        classText = element.className || '';
        tag = element.tagName ? element.tagName.toLowerCase() : '';
      }
      var position = '';
      if (event && typeof event.clientX === 'number') {
        position = Math.round(event.clientX) + ',' + Math.round(event.clientY);
      }
      emit('click', {
        class: classText,
        tag: tag,
        position: position,
        result: (extra && extra.result) || 'ok',
        message: (extra && extra.message) || ''
      });
    },
    info: function (event, fields) {
      emit(event, fields);
    },
    error: function (event, fields) {
      emit(event, fields);
    },
    jsVersion: function () {
      return JS_VERSION;
    }
  };

  /* 全局脚本错误捕获：仅在 DEBUG 模式输出，用于溯源第三方/未知脚本报错。
   * 记录 message / 来源文件 / 行号 / 列号 / 调用栈。 */
  function logGlobalError(message, source, lineno, colno, error) {
    emit('script_error', {
      kind: 'window.onerror',
      message: message || '',
      source: source || '',
      lineno: lineno || '',
      colno: colno || '',
      stack: (error && error.stack) ? error.stack : ''
    });
  }

  function logUnhandledRejection(reason) {
    var message = '';
    var stack = '';
    if (reason) {
      message = reason.message || String(reason);
      stack = reason.stack || '';
    }
    emit('script_error', {
      kind: 'unhandledrejection',
      message: message,
      source: '',
      lineno: '',
      colno: '',
      stack: stack
    });
  }

  global.onerror = function (message, source, lineno, colno, error) {
    logGlobalError(message, source, lineno, colno, error);
  };
  global.addEventListener('unhandledrejection', function (event) {
    logUnhandledRejection(event && event.reason);
  });

  global.RtDebug = DebugLogger;
})(window);
