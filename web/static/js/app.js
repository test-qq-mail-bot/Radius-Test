/* 应用入口：路由、公共 UI 组件与全局初始化。 */
(function (global) {
  'use strict';

  var PAGES = ['home', 'server', 'user', 'perf', 'result', 'parse', 'dict', 'config'];
  var currentPage = 'home';
  var refreshHandler = null;

  var UI = {
    card: function (title, actions) {
      var element = document.createElement('section');
      element.className = 'app-card';
      var header = document.createElement('div');
      header.className = 'app-card-header';
      var titleNode = document.createElement('span');
      titleNode.className = 'app-card-title';
      titleNode.textContent = title;
      header.appendChild(titleNode);
      if (actions && actions.length) {
        var actionHost = document.createElement('div');
        actionHost.className = 'app-card-actions';
        actions.forEach(function (action) {
          actionHost.appendChild(action);
        });
        header.appendChild(actionHost);
      }
      var body = document.createElement('div');
      body.className = 'app-card-body';
      element.appendChild(header);
      element.appendChild(body);
      return { element: element, body: body };
    },

    /* 按钮统一无图标。
       原因：图标是 <img>，在蓝色主按钮上完全不可见，且会撑出多余空白。
       按需求移除全部按钮图标；导航图标与表格排序/筛选图标属功能性图标，不受影响。 */
    button: function (text, kind, size) {
      var button = document.createElement('button');
      var classes = ['app-button'];
      if (kind) {
        classes.push('app-button-' + kind);
      }
      if (size === 'sm') {
        classes.push('app-button-sm');
      } else if (size === 'lg') {
        classes.push('app-button-lg');
      }
      button.className = classes.join(' ');
      button.type = 'button';
      var span = document.createElement('span');
      span.className = 'app-button-text';
      span.textContent = text;
      button.appendChild(span);
      return button;
    },

    /* 密钥/密码输入框：默认密文，点击眼睛按钮可暂时查看已输入内容。
       返回容器 div（内含 input 与切换按钮），input 仍带 app-field-input 类，
       以兼容表单读取与校验逻辑。 */
    secretInput: function (name, value, id) {
      var wrap = document.createElement('div');
      wrap.className = 'app-secret-input';
      var element = document.createElement('input');
      element.className = 'app-field-input app-secret-input-field';
      element.name = name;
      element.type = 'password';
      element.value = value === undefined || value === null ? '' : String(value);
      element.setAttribute('autocomplete', 'new-password');
      if (id) {
        element.id = id;
      }
      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'app-secret-toggle';
      toggle.title = '显示 / 隐藏';
      toggle.setAttribute('aria-label', '显示或隐藏内容');
      toggle.setAttribute('aria-pressed', 'false');
      var icon = document.createElement('img');
      icon.className = 'app-secret-toggle-icon';
      icon.src = '/static/svg/action-eye.svg';
      icon.alt = '';
      toggle.appendChild(icon);
      toggle.addEventListener('click', function () {
        var show = element.type === 'password';
        element.type = show ? 'text' : 'password';
        icon.src = show ? '/static/svg/action-eye-off.svg' : '/static/svg/action-eye.svg';
        toggle.setAttribute('aria-pressed', show ? 'true' : 'false');
      });
      wrap.appendChild(element);
      wrap.appendChild(toggle);
      return wrap;
    },

    toast: function (message, kind) {
      var host = document.getElementById('toast-host');
      if (!host) {
        return;
      }
      var kindName = kind || 'info';
      var node = document.createElement('div');
      node.className = 'app-toast app-toast-' + kindName;
      node.title = '点击复制内容';
      var textSpan = document.createElement('span');
      textSpan.className = 'app-toast-text';
      textSpan.textContent = message;
      node.appendChild(textSpan);
      if (kindName === 'error' || kindName === 'warning') {
        // 错误/警告提示内置复制按钮，方便拷贝错误码
        var copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'app-toast-copy';
        copyBtn.title = '复制内容';
        copyBtn.setAttribute('aria-label', '复制内容');
        copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
          + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
          + 'stroke-linejoin="round" aria-hidden="true">'
          + '<rect x="9" y="9" width="13" height="13" rx="2"/>'
          + '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
        copyBtn.addEventListener('click', function (event) {
          event.stopPropagation();
          UI._copyToast(node, textSpan.textContent);
        });
        node.appendChild(copyBtn);
      }
      // 点击提示条任意位置即复制全文
      node.addEventListener('click', function () {
        UI._copyToast(node, textSpan.textContent);
      });
      host.appendChild(node);
      // 错误/警告停留更久，便于查看与复制
      var duration = (kindName === 'error' || kindName === 'warning') ? 10000 : 3200;
      setTimeout(function () {
        if (node.parentNode) {
          node.parentNode.removeChild(node);
        }
      }, duration);
      if (global.RtDebug) {
        global.RtDebug.info('toast', { message: message, kind: kindName });
      }
    },

    /* 复制提示条内容，成功后短暂显示“已复制”反馈 */
    _copyToast: function (node, text) {
      var done = function () {
        node.classList.add('app-toast-copied');
        setTimeout(function () {
          node.classList.remove('app-toast-copied');
        }, 1200);
      };
      if (global.navigator && global.navigator.clipboard
        && global.navigator.clipboard.writeText) {
        global.navigator.clipboard.writeText(text).then(done, function () {
          UI._copyToastFallback(text, done);
        });
      } else {
        UI._copyToastFallback(text, done);
      }
    },

    /* 剪贴板 API 不可用时的降级：隐藏 textarea + execCommand */
    _copyToastFallback: function (text, done) {
      var area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand('copy');
        done();
      } catch (err) {
        /* 忽略复制失败 */
      }
      document.body.removeChild(area);
    },

    /* 按钮级 loading：只在按钮内部显示 spinner，不使用全页蒙层 */
    withLoading: function (button, task, event) {
      var original = button.innerHTML;
      button.disabled = true;
      button.innerHTML = '';
      var spinner = document.createElement('span');
      spinner.className = 'app-button-spinner';
      button.appendChild(spinner);
      if (global.RtDebug) {
        global.RtDebug.click(button, event, { result: 'start' });
      }
      return Promise.resolve().then(task).then(function (result) {
        button.innerHTML = original;
        button.disabled = false;
        if (global.RtDebug) {
          global.RtDebug.click(button, event, { result: 'ok' });
        }
        return result;
      }, function (error) {
        button.innerHTML = original;
        button.disabled = false;
        UI.toast(error && error.message ? error.message : '操作失败', 'error');
        if (global.RtDebug) {
          global.RtDebug.click(button, event, { result: 'error', message: String(error) });
        }
        throw error;
      });
    },

    modal: function (title, pairs, buttons, customBody) {
      var host = document.getElementById('modal-host');
      var titleNode = document.getElementById('modal-title');
      var bodyNode = document.getElementById('modal-body');
      var footerNode = document.getElementById('modal-footer');
      titleNode.textContent = title;
      bodyNode.innerHTML = '';
      footerNode.innerHTML = '';
      // 每次打开弹窗先清掉上一次的加宽标记，避免影响其他弹窗
      var panelNode = document.getElementById('modal-panel');
      if (panelNode) {
        panelNode.classList.remove('is-wide');
      }

      if (customBody) {
        bodyNode.appendChild(customBody);
      } else if (pairs && pairs.length) {
        var list = document.createElement('div');
        list.className = 'app-detail-list';
        pairs.forEach(function (pair) {
          var item = document.createElement('div');
          item.className = 'app-detail-item';
          var key = document.createElement('span');
          key.className = 'app-detail-key';
          key.textContent = pair[0];
          var value = document.createElement('span');
          value.className = 'app-detail-value';
          value.textContent = String(pair[1] === undefined || pair[1] === null ? '-' : pair[1]);
          item.appendChild(key);
          item.appendChild(value);
          list.appendChild(item);
        });
        bodyNode.appendChild(list);
      }

      var actions = buttons && buttons.length ? buttons : [];
      if (actions.length === 0) {
        var close = UI.button('关闭', '');
        close.addEventListener('click', function () {
          UI.closeModal();
        });
        actions = [close];
      }
      actions.forEach(function (action) {
        footerNode.appendChild(action);
      });
      host.hidden = false;
      return host;
    },

    closeModal: function () {
      var host = document.getElementById('modal-host');
      if (host) {
        host.hidden = true;
      }
    },

    confirm: function (title, message, pairs) {
      return new Promise(function (resolve) {
        var okButton = UI.button('确定', 'primary');
        var cancelButton = UI.button('取消', '');
        okButton.addEventListener('click', function () {
          UI.closeModal();
          resolve(true);
        });
        cancelButton.addEventListener('click', function () {
          UI.closeModal();
          resolve(false);
        });
        var body = null;
        if (pairs && pairs.length) {
          body = document.createElement('div');
          var list = document.createElement('div');
          list.className = 'app-detail-list';
          pairs.forEach(function (pair) {
            var item = document.createElement('div');
            item.className = 'app-detail-item';
            var key = document.createElement('span');
            key.className = 'app-detail-key';
            key.textContent = pair[0];
            var value = document.createElement('span');
            value.className = 'app-detail-value';
            value.textContent = String(pair[1] === undefined || pair[1] === null ? '-' : pair[1]);
            item.appendChild(key);
            item.appendChild(value);
            list.appendChild(item);
          });
          body.appendChild(list);
        } else if (message) {
          body = document.createElement('div');
          body.className = 'app-detail-value';
          body.textContent = message;
        }
        UI.modal(title, [], [cancelButton, okButton], body);
      });
    },

    bindRefresh: function (handler) {
      refreshHandler = handler;
    },

    /* 表单校验工具：
     *   - rules：内置规则（required / host / port / positive）
     *   - runRules(rules, value, label)：按顺序跑规则，返回首个错误信息或 null
     *   - validateField(box, value, rules, label)：给字段容器添加/清除 is-invalid 与错误提示
     *   - validateForm(form, schema)：批量校验表单，返回 { valid, errors }
     *   - bindLiveValidation(form, schema)：绑定失焦/输入时的实时校验
     */
    validate: {
      rules: {
        required: function (value, label) {
          if (value === undefined || value === null || String(value).trim() === '') {
            return label + '不能为空';
          }
          return null;
        },
        host: function (value, label) {
          var v = String(value || '').trim();
          if (!v) return label + '不能为空';
          if (/^(\d{1,3}\.){3}\d{1,3}$/.test(v)) {
            var ok = v.split('.').every(function (part) {
              var n = parseInt(part, 10);
              return n >= 0 && n <= 255;
            });
            return ok ? null : (label + '不是有效的 IPv4');
          }
          if (v.indexOf(':') >= 0) return null;
          if (/^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)+$/.test(v)) {
            return null;
          }
          return label + '格式不正确（需为 IP 或域名）';
        },
        port: function (value, label) {
          var n = parseInt(value, 10);
          if (isNaN(n) || n < 1 || n > 65535) return label + '需在 1~65535 之间';
          return null;
        },
        positiveNumber: function (value, label, min, max) {
          var n = parseFloat(value);
          if (isNaN(n)) return label + '必须是数字';
          if (min !== undefined && n < min) return label + '需 ≥ ' + min;
          if (max !== undefined && n > max) return label + '需 ≤ ' + max;
          return null;
        },
        integer: function (value, label, min, max) {
          if (!String(value).trim()) return null;
          var n = parseInt(value, 10);
          if (isNaN(n) || String(n) !== String(value).trim()) return label + '必须是整数';
          if (min !== undefined && n < min) return label + '需 ≥ ' + min;
          if (max !== undefined && n > max) return label + '需 ≤ ' + max;
          return null;
        },
        pattern: function (value, label, pattern, hint) {
          if (!String(value).trim()) return null;
          var re = new RegExp(pattern);
          return re.test(value) ? null : (label + (hint || '格式不正确'));
        }
      },
      runRules: function (rules, value, label) {
        if (!rules) return null;
        var isEmpty = value === undefined || value === null || String(value).trim() === '';
        for (var i = 0; i < rules.length; i++) {
          var rule = rules[i];
          if (rule.optional && isEmpty) continue;
          var fn = this.rules[rule.type];
          if (!fn) continue;
          var msg = fn(value, label, rule.min, rule.max, rule.pattern, rule.hint);
          if (msg) return msg;
        }
        return null;
      },
      showError: function (box, message) {
        box.classList.add('is-invalid');
        var old = box.querySelector('.app-field-error');
        if (old) old.parentNode.removeChild(old);
        if (message) {
          var node = document.createElement('span');
          node.className = 'app-field-error';
          node.textContent = message;
          box.appendChild(node);
        }
      },
      clearError: function (box) {
        box.classList.remove('is-invalid');
        var old = box.querySelector('.app-field-error');
        if (old) old.parentNode.removeChild(old);
      },
      /* 校验并显示单个字段错误。返回 true 表示通过。 */
      checkField: function (box) {
        var schema = box._validateSchema;
        if (!schema) return true;
        var input = box.querySelector('.app-field-input, .app-field-select, .app-field-textarea');
        if (!input) return true;
        var value = input.type === 'checkbox' ? input.checked : input.value;
        var msg = this.runRules(schema.rules, value, schema.label);
        if (msg) {
          this.showError(box, msg);
          return false;
        }
        this.clearError(box);
        return true;
      },
      /* 直接校验单个 input（不依赖 box 容器），返回错误信息或 null */
      checkInput: function (input, schema) {
        if (!schema) return null;
        var value = input.type === 'checkbox' ? input.checked : input.value;
        return this.runRules(schema.rules, value, schema.label);
      },
      /* 给 input 绑定 schema 与失焦校验。错误时给 input 加 is-invalid 类 */
      bindInput: function (input, schema) {
        input._validateSchema = schema;
        var self = this;
        var handler = function () {
          var msg = self.checkInput(input, schema);
          input.classList.toggle('is-invalid', !!msg);
        };
        input.addEventListener('blur', handler);
        input.addEventListener('change', handler);
      },
      /* 校验整个表单（按 schema 数组），返回 { valid, firstInvalid } */
      validateForm: function (boxes) {
        var valid = true;
        var firstInvalid = null;
        boxes.forEach(function (box) {
          if (!this.checkField(box)) {
            valid = false;
            if (!firstInvalid) firstInvalid = box;
          }
        }.bind(this));
        return { valid: valid, firstInvalid: firstInvalid };
      },
      /* 给字段容器绑定 schema 与实时校验事件 */
      bindField: function (box, schema) {
        box._validateSchema = schema;
        var input = box.querySelector('.app-field-input, .app-field-select, .app-field-textarea');
        if (!input) return;
        var self = this;
        var handler = function () { self.checkField(box); };
        input.addEventListener('blur', handler);
        input.addEventListener('change', handler);
        // 输入时清掉错误样式，但首次提交前不重跑规则（避免红框闪烁）
        input.addEventListener('input', function () {
          if (box.classList.contains('is-invalid')) {
            // 不重跑，保留错误直到 blur
          }
        });
      }
    }
  };

  global.RtUI = UI;

  function setActiveNav(page) {
    Array.prototype.forEach.call(document.querySelectorAll('.app-nav-item'), function (item) {
      if (item.dataset.page === page) {
        item.classList.add('is-active');
      } else {
        item.classList.remove('is-active');
      }
    });
  }

  function renderPage(page) {
    var container = document.getElementById('app-content');
    var titleNode = document.getElementById('page-title');
    var descNode = document.getElementById('page-desc');
    var module = (global.RtPages || {})[page];
    if (!module) {
      page = 'home';
      module = global.RtPages.home;
    }
    currentPage = page;
    if (global.RtDebug) {
      global.RtDebug.setPage(page);
    }
    setActiveNav(page);
    titleNode.textContent = module.title || '';
    descNode.textContent = module.desc || '';
    container.innerHTML = '';
    var loading = document.createElement('div');
    loading.className = 'app-loading';
    loading.textContent = '加载中';
    container.appendChild(loading);
    Promise.resolve().then(function () {
      return module.render(container);
    }).then(function () {
      var stale = container.querySelector('.app-loading');
      if (stale) {
        stale.remove();
      }
    }).catch(function (error) {
      container.innerHTML = '';
      var errorNode = document.createElement('div');
      errorNode.className = 'app-table-empty';
      errorNode.textContent = '页面加载失败：' + (error && error.message ? error.message : error);
      container.appendChild(errorNode);
    });
    if (history.replaceState) {
      history.replaceState(null, '', '#/' + page);
    } else {
      location.hash = '#/' + page;
    }
  }

  function currentRoute() {
    var hash = location.hash || '';
    var match = /^#\/([a-z]+)/.exec(hash);
    if (match && PAGES.indexOf(match[1]) >= 0) {
      return match[1];
    }
    return 'home';
  }

  function showListenWarning(info) {
    var host = document.getElementById('listen-warning');
    var textNode = document.getElementById('listen-warning-text');
    var listen = info.listen || {};
    if (listen.local_only === false || info.local_only === false) {
      textNode.textContent = '请确认当前网络环境可信，否则请改回127.0.0.1和::1';
      host.hidden = false;
    } else {
      host.hidden = true;
    }
  }

  function init() {
    global.addEventListener('hashchange', function () {
      renderPage(currentRoute());
    });

    var refreshButton = document.getElementById('header-refresh-button');
    if (refreshButton) {
      refreshButton.addEventListener('click', function (event) {
        if (global.RtDebug) {
          global.RtDebug.click(refreshButton, event, { result: 'ok' });
        }
        renderPage(currentPage);
      });
    }

    var mask = document.getElementById('modal-mask');
    var closeButton = document.getElementById('modal-close');
    if (mask) {
      mask.addEventListener('click', function () {
        UI.closeModal();
      });
    }
    if (closeButton) {
      closeButton.addEventListener('click', function () {
        UI.closeModal();
      });
    }

    global.RtApi.systemInfo().then(function (info) {
      document.title = (info.software_name || 'Radius-Test') +
        ' ' + (info.software_version || '');
      var nameNode = document.getElementById('sidebar-software-name');
      var versionNode = document.getElementById('sidebar-software-version');
      if (nameNode) {
        nameNode.textContent = info.software_name || 'Radius-Test';
      }
      if (versionNode) {
        versionNode.textContent = info.software_version || '';
      }
      var pyNode = document.getElementById('sidebar-python-version');
      if (pyNode) {
        pyNode.textContent = info.python_version || '--';
      }
      var platformNode = document.getElementById('sidebar-platform');
      if (platformNode) {
        var plat = info.platform || '';
        platformNode.textContent = plat.length > 22 ? plat.slice(0, 22) + '...' : plat;
      }
      if (global.RtDebug) {
        global.RtDebug.setSoftwareVersion(info.software_version);
        if (info.frontend_version) {
          global.RtDebug.setJsVersion(info.frontend_version);
        }
      }
      var headerStatus = document.getElementById('header-status');
      if (headerStatus) {
        var localTxt = info.local_only ? '本机' : '远程';
        var httpsTxt = info.https_enabled ? 'HTTPS' : 'HTTP';
        headerStatus.textContent = localTxt + ' · ' + httpsTxt;
        headerStatus.classList.toggle('is-warn', !info.local_only);
      }
      showListenWarning(info);
      /* 后端日志等级为 DEBUG 时开启前端 Debug 输出 */
      return global.RtApi.getConfig();
    }).then(function (data) {
      var level = ((data.config || {}).log || {}).level || 'INFO';
      if (global.RtDebug) {
        global.RtDebug.setEnabled(String(level).toUpperCase() === 'DEBUG');
      }
    }).catch(function (error) {
      UI.toast('系统信息加载失败：' + (error && error.message ? error.message : error), 'error');
    });

    global.RtWs.connect();
    renderPage(currentRoute());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
