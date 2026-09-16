/* 应用入口：路由、公共 UI 组件与全局初始化。 */
(function (global) {
  'use strict';

  var PAGES = ['home', 'server', 'user', 'perf', 'result', 'dict', 'config'];
  var currentPage = 'home';
  var refreshHandler = null;

  /* 测试页面集合：只有停在这些页面上时，测试才允许继续运行（需求5）。
     与后端 src/web/page_liveness.py 的 TEST_PAGES 保持一致。 */
  var TEST_PAGES = ['perf', 'server'];
  /* 测试页面心跳间隔，与后端 HEARTBEAT_INTERVAL 保持一致 */
  var PAGE_HEARTBEAT_INTERVAL = 2000;
  var pageHeartbeatTimer = null;
  var heartbeatPage = '';

  /* 停止测试页面心跳；leftPage 有值时一并向后端声明「已离开测试页面」，
     后端收到后立即中断测试，不等心跳超时。 */
  function stopPageHeartbeat(leftPage) {
    if (pageHeartbeatTimer) {
      clearInterval(pageHeartbeatTimer);
      pageHeartbeatTimer = null;
    }
    heartbeatPage = '';
    if (leftPage && global.RtApi && global.RtApi.pageLeave) {
      global.RtApi.pageLeave(leftPage).catch(function () { /* 失败由心跳超时兜底 */ });
    }
  }

  /* 每次进入页面时同步心跳：
     测试页面 -> 立即上报一次并启动 2 秒周期心跳；
     非测试页面 -> 停表，若此前停在测试页面则立即上报离开。
     注意：不监听 visibilitychange / blur，窗口切到后台不算离开。 */
  function syncPageHeartbeat(page) {
    if (TEST_PAGES.indexOf(page) >= 0) {
      if (pageHeartbeatTimer) {
        clearInterval(pageHeartbeatTimer);
        pageHeartbeatTimer = null;
      }
      heartbeatPage = page;
      var beat = function () {
        if (!heartbeatPage || !global.RtApi) {
          return;
        }
        global.RtApi.heartbeat(heartbeatPage).catch(function () { /* 超时兜底 */ });
      };
      beat();
      pageHeartbeatTimer = setInterval(beat, PAGE_HEARTBEAT_INTERVAL);
      return;
    }
    stopPageHeartbeat(heartbeatPage);
  }

  /* 已分配过的 id 集合。
     只用 document.getElementById 判重是不够的：尚未插入文档的元素
     （如先建后挂的卡片、弹窗内容）查不到，会出现重名。
     因此维护一份全局登记表，保证全站 id 唯一。 */
  var USED_IDS = {};

  /* 生成页面内唯一 id（供自动化/测试定位元素使用）。
     对 base 做合法字符清洗，并在已登记时追加序号保证唯一。 */
  function uid(base) {
    base = String(base).replace(/[^A-Za-z0-9_-]/g, '_');
    if (!base || /^[0-9]/.test(base)) base = 'e' + base;
    var n = 1, id = base;
    while (USED_IDS[id] || document.getElementById(id)) { id = base + '-' + (++n); }
    USED_IDS[id] = true;
    return id;
  }
  global.uid = uid;

  /* Dot1X 接入配置助手。
     账号认证测试（Server 列表单用户测试 / 用户列表单个与批量测试）统一使用，
     避免各页面各写一份、字段名不一致。

     约定（2026-09-15 用户确认的口径）：
       - 接入类型默认「有线」；
       - SSID 仅无线使用，留空由后端置为 Radius-Test；
       - 其余字段（NAS-Port / NAS-Port-Id / 终端 MAC / NAS-Identifier / Connect-Info）
         **全部可自定义；留空时由后端生成默认合法值并发送出去，不存在「留空不发送」**；
       - NAS-Port(5) 是端口号（数值），NAS-Port-Id(87) 是端口名称（字符串），二者互不相干。 */
  var Dot1x = {
    /* 构造传给后端的 dot1x 参数。
       入参为 createPanel() 返回的字段对象；留空字段一律传空串，
       由后端 builder.resolve_dot1x() 统一补齐默认合法值。 */
    build: function (fields) {
      fields = fields || {};
      function val(key) {
        var node = fields[key];
        return node ? String(node.value || '').trim() : '';
      }
      var wireless = val('accessType').toLowerCase() === 'wireless';
      return {
        access_type: wireless ? 'wireless' : 'wired',
        ssid: wireless ? val('ssid') : '',
        nas_port: val('nasPort'),
        nas_port_id: val('nasPortId'),
        calling_station_id: val('mac'),
        nas_identifier: val('nasIdentifier'),
        service_type: val('serviceType'),
        framed_ip_address: val('framedIp'),
        connect_info: val('connectInfo')
      };
    },
    /* 接入类型下拉选项：[值, 显示文本]。 */
    accessOptions: function () {
      return [['wired', '有线'], ['wireless', '无线']];
    },
    /* Service-Type(6) 选项：[值, 显示文本]；空值表示使用默认值 Framed(2)。
       注意：Administrative(6) 会被部分服务端静默丢弃（实测 AgileController 完全不回包，
       客户端表现为认证无响应），因此默认值取场景标准的 Framed(2)，不做随机。 */
    serviceOptions: function () {
      return [
        ['', '默认 Framed (2)'],
        ['1', 'Login (1)'],
        ['2', 'Framed (2)'],
        ['3', 'Callback-Login (3)'],
        ['4', 'Callback-Framed (4)'],
        ['5', 'Outbound (5)'],
        ['6', 'Administrative (6) - 部分服务端不响应'],
        ['7', 'NAS-Prompt (7)'],
        ['8', 'Authenticate-Only (8)'],
        ['9', 'Callback-NAS-Prompt (9)'],
        ['10', 'Call-Check (10)']
      ];
    },
    /* 创建下拉控件；options 为 [值, 显示文本] 数组。 */
    createSelect: function (id, options, value) {
      var sel = document.createElement('select');
      sel.className = 'app-field-select';
      if (id) { sel.id = id; }
      options.forEach(function (pair) {
        var opt = document.createElement('option');
        opt.value = pair[0];
        opt.textContent = pair[1];
        sel.appendChild(opt);
      });
      if (value !== undefined) { sel.value = value; }
      return sel;
    },
    /* 创建接入类型下拉（默认有线）。 */
    createAccessSelect: function (id) {
      return Dot1x.createSelect(id, Dot1x.accessOptions(), 'wired');
    },
    /* 创建 Dot1X 接入配置面板。
       返回 { element, fields }；fields 键名：
         accessType / ssid / nasPort / nasPortId / mac /
         nasIdentifier / serviceType / framedIp / connectInfo
       说明：NAS-Port(5) 是端口号（数值），NAS-Port-Id(87) 是端口名称（字符串），
       二者语义不同，因此拆成两个独立输入框。
       exclude：需要隐藏的字段键名数组（通用能力，当前三个测试入口都不排除任何字段，
         面板字段完全一致：接入类型 / SSID / NAS-Port / NAS-Port-Id / 终端 MAC /
         NAS-Identifier / Service-Type / Framed-IP-Address / Connect-Info）。 */
    createPanel: function (prefix, exclude) {
      prefix = String(prefix || 'app-dot1x');
      var excludes = exclude || [];

      function textField(hint) {
        var input = document.createElement('input');
        input.className = 'app-field-input';
        input.type = 'text';
        input.setAttribute('autocomplete', 'off');
        if (hint) { input.setAttribute('placeholder', hint); }
        return input;
      }
      function field(label, control, hint) {
        var box = document.createElement('div');
        box.className = 'app-field';
        var l = document.createElement('label');
        l.className = 'app-field-label';
        l.textContent = label;
        box.appendChild(l);
        box.appendChild(control);
        if (hint) {
          var h = document.createElement('span');
          h.className = 'app-field-hint';
          h.textContent = hint;
          box.appendChild(h);
        }
        return box;
      }
      function row() {
        var r = document.createElement('div');
        r.className = 'app-form-row';
        return r;
      }

      var panel = document.createElement('div');
      panel.className = 'app-dot1x-panel';
      panel.id = uid(prefix + '-panel');

      var fields = {
        accessType: Dot1x.createAccessSelect(uid(prefix + '-accesstype')),
        ssid: textField('Radius-Test'),
        nasPort: textField('留空则默认生成'),
        nasPortId: textField('如 GigabitEthernet0/0/1'),
        mac: textField('留空则默认生成'),
        nasIdentifier: textField('如 nas-1a2b'),
        serviceType: Dot1x.createSelect(uid(prefix + '-servicetype'),
          Dot1x.serviceOptions(), ''),
        framedIp: textField('如 10.0.0.1；留空则默认生成'),
        connectInfo: textField('留空则默认生成')
      };
      fields.ssid.id = uid(prefix + '-ssid');
      fields.nasPort.id = uid(prefix + '-nasport');
      fields.nasPortId.id = uid(prefix + '-nasportid');
      fields.mac.id = uid(prefix + '-mac');
      fields.nasIdentifier.id = uid(prefix + '-nasidentifier');
      fields.framedIp.id = uid(prefix + '-framedip');
      fields.connectInfo.id = uid(prefix + '-connectinfo');

      var ssidBox = field('SSID（无线）', fields.ssid, '仅无线接入使用；留空默认为 Radius-Test');
      function syncSsid() {
        var wireless = fields.accessType.value === 'wireless';
        fields.ssid.disabled = !wireless;
        ssidBox.hidden = !wireless;
      }
      fields.accessType.addEventListener('change', syncSsid);
      syncSsid();

      var rowA = row();
      rowA.appendChild(field('Dot1X 接入类型', fields.accessType));
      rowA.appendChild(ssidBox);
      panel.appendChild(rowA);

      var rowB = row();
      rowB.appendChild(field('NAS-Port（端口号，数值）', fields.nasPort,
        '属性 5；留空则默认生成合法值'));
      rowB.appendChild(field('NAS-Port-Id（端口名称，字符串）', fields.nasPortId,
        '属性 87；留空则默认生成合法值'));
      rowB.appendChild(field('终端 MAC', fields.mac, '属性 31；留空则默认生成合法值'));
      panel.appendChild(rowB);

      var rowC = row();
      rowC.appendChild(field('NAS-Identifier', fields.nasIdentifier,
        '属性 32；留空则默认生成合法值'));
      if (excludes.indexOf('serviceType') < 0) {
        rowC.appendChild(field('Service-Type', fields.serviceType, '属性 6；留空默认 Framed(2)'));
      }
      if (excludes.indexOf('framedIp') < 0) {
        rowC.appendChild(field('Framed-IP-Address', fields.framedIp, '属性 8；留空则默认生成合法值'));
      }
      // Connect-Info(77)：留空由后端生成默认合法值
      rowC.appendChild(field('Connect-Info', fields.connectInfo,
        '属性 77；留空则默认生成合法值'));
      panel.appendChild(rowC);

      return { element: panel, fields: fields };
    }
  };
  global.RtDot1x = Dot1x;

  /* 中文字段显示回退：内置字典里部分属性的 name_zh 尚未翻译（与英文名相同，
     或纯英文无汉字）。这类情况直接返回空串，避免「Name」与「Name_ZH」两列
     显示一模一样的英文，造成"满屏英文"的观感。
     含中文（含「中文译名（English原名）」双语格式）的才正常展示。 */
  function dictDisplayNameZh(name, nameZh) {
    nameZh = nameZh || '';
    if (!nameZh || nameZh === (name || '')) return '';
    return /[一-鿿]/.test(nameZh) ? nameZh : '';
  }
  global.dictDisplayNameZh = dictDisplayNameZh;

  /* 不需要命名的标签：脚本、样式、文档级元信息 */
  var UNNAMED_TAGS = {
    script: 1, style: 1, meta: 1, link: 1, title: 1, head: 1, html: 1, base: 1
  };

  /* 为无 id 的元素生成兜底 id。
     命名规则：app-el-<标签>-<首个类名>，重复时由 uid() 追加序号。
     这样「文本、图片、表头、单元格、下拉选项」等任意元素都有唯一 id，
     需要语义化命名的关键组件仍由各页面显式指定。 */
  function nameElement(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.hasAttribute('id')) return;
    var tag = String(node.tagName || '').toLowerCase();
    if (UNNAMED_TAGS[tag]) return;
    var cls = (typeof node.className === 'string' && node.className)
      ? node.className.split(' ')[0] : '';
    node.id = uid('app-el-' + tag + (cls ? '-' + cls : ''));
  }

  /* 遍历子树，补齐全部缺失的 id */
  function nameElements(root) {
    if (!root || root.nodeType !== 1) return;
    nameElement(root);
    var nodes = root.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i += 1) {
      nameElement(nodes[i]);
    }
  }
  global.RtNameElements = nameElements;

  /* 监听后续动态插入的节点（表格行、弹窗、提示条、实时指标等），
     保证运行过程中产生的元素同样具备唯一 id。 */
  function watchNewElements() {
    if (typeof MutationObserver !== 'function') return;
    var observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        Array.prototype.forEach.call(record.addedNodes, function (node) {
          nameElements(node);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

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
      var actionHost = null;
      if (actions && actions.length) {
        actionHost = document.createElement('div');
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
      /* 一次性命名卡片及其内部结构：卡片/id、标题/id-title、主体/id-body、
         操作区/id-actions，保证卡片内每个元素都有可定位的唯一 id。 */
      var card = {
        element: element,
        body: body,
        identify: function (prefix) {
          element.id = uid(prefix);
          header.id = element.id + '-header';
          titleNode.id = element.id + '-title';
          body.id = element.id + '-body';
          if (actionHost) {
            actionHost.id = element.id + '-actions';
          }
          return element.id;
        }
      };
      return card;
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
        wrap.id = id + '-wrap';
      }
      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'app-secret-toggle';
      if (id) {
        toggle.id = id + '-toggle';
      }
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
      node.id = global.uid('app-toast');
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
        copyBtn.id = node.id + '-copy';
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

    /* 弹窗宽度档位：
         options.width = 'wide'   加宽（测试详情、参数较多的大弹窗）
         options.width = 'medium' 中等（短键值列表，如确认弹窗）
       每次打开都会先清掉上一档，避免影响其他弹窗。 */
    modal: function (title, pairs, buttons, customBody, options) {
      var host = document.getElementById('modal-host');
      var titleNode = document.getElementById('modal-title');
      var bodyNode = document.getElementById('modal-body');
      var footerNode = document.getElementById('modal-footer');
      titleNode.textContent = title;
      bodyNode.innerHTML = '';
      footerNode.innerHTML = '';
      var panelNode = document.getElementById('modal-panel');
      if (panelNode) {
        panelNode.classList.remove('is-wide', 'is-medium');
        var width = (options || {}).width;
        if (width === 'wide') {
          panelNode.classList.add('is-wide');
        } else if (width === 'medium') {
          panelNode.classList.add('is-medium');
        }
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
        close.id = global.uid('app-modal-close-default');
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
      // 同步清掉宽度档：否则下次不带档位打开时，会残留上一次的宽度，
      // 且 is-medium 定义在 is-wide 之后，会覆盖测试详情等弹窗的加宽效果。
      var panelNode = document.getElementById('modal-panel');
      if (panelNode) {
        panelNode.classList.remove('is-wide', 'is-medium');
      }
    },

    /* 二次确认弹窗。options 透传给 modal，支持 { width: 'medium' | 'wide' }。 */
    confirm: function (title, message, pairs, options) {
      return new Promise(function (resolve) {
        var okButton = UI.button('确定', 'primary');
        okButton.id = global.uid('app-confirm-ok');
        var cancelButton = UI.button('取消', '');
        cancelButton.id = global.uid('app-confirm-cancel');
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
        UI.modal(title, [], [cancelButton, okButton], body, options);
      });
    },

    bindRefresh: function (handler) {
      refreshHandler = handler;
    },

    /* 让整块 .app-checkbox-row 可点击切换勾选态（不只点小框）。
       行内只有一个复选框 + 标签时安全；点击复选框本身由浏览器原生处理，避免重复切换。 */
    bindCheckboxRows: function (container) {
      if (!container) return;
      var rows = container.querySelectorAll('.app-checkbox-row');
      Array.prototype.forEach.call(rows, function (row) {
        if (row._checkboxRowBound) return;
        row._checkboxRowBound = true;
        row.addEventListener('click', function (event) {
          var cb = row.querySelector('input[type="checkbox"]');
          if (!cb || event.target === cb) return;
          cb.checked = !cb.checked;
          var ev = document.createEvent('HTMLEvents');
          ev.initEvent('change', true, true);
          cb.dispatchEvent(ev);
        });
      });
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

  /* 账号认证测试（保持在线）状态条。
   * 需求3/5：所有账号认证测试点击后保持用户在线；点「停止测试」或前端断开时取消。
   * 由用户列表「测试/批量测试」与 Server「Radius 用户测试」共同登记在线会话。 */
  var UserTest = (function () {
    var active = [];
    var banner = null;
    var textNode = null;

    function ensureBanner() {
      if (banner) {
        return banner;
      }
      banner = document.createElement('div');
      banner.id = 'app-usertest-banner';
      banner.className = 'app-usertest-banner';
      banner.hidden = true;
      textNode = document.createElement('span');
      textNode.id = 'app-usertest-banner-text';
      textNode.className = 'app-usertest-banner-text';
      var stopBtn = document.createElement('button');
      stopBtn.id = 'app-usertest-banner-stop';
      stopBtn.className = 'app-button app-button-danger app-button-sm';
      stopBtn.type = 'button';
      stopBtn.textContent = '停止测试';
      stopBtn.addEventListener('click', function () {
        UI.confirm('停止账号认证测试', '确认停止全部账号认证测试并发送 Accounting-Stop？')
          .then(function (confirmed) {
            if (!confirmed) {
              return null;
            }
            return stopAll();
          });
      });
      banner.appendChild(textNode);
      banner.appendChild(stopBtn);
      document.body.appendChild(banner);
      return banner;
    }

    function render() {
      var node = ensureBanner();
      if (!active.length) {
        node.hidden = true;
        textNode.textContent = '';
        return;
      }
      node.hidden = false;
      var names = active.map(function (item) { return item.username; })
        .filter(function (name) { return !!name; });
      var shown = names.slice(0, 5).join('、');
      if (names.length > 5) {
        shown += ' 等';
      }
      textNode.textContent = '账号认证测试进行中（保持在线）：' + active.length + ' 个会话'
        + (shown ? '（' + shown + '）' : '');
    }

    function add(result, serverName) {
      if (!result || !result.online || !result.session_id) {
        return;
      }
      var exists = active.some(function (item) {
        return item.session_id === result.session_id;
      });
      if (exists) {
        return;
      }
      active.push({
        session_id: result.session_id,
        task_id: result.task_id,
        username: result.username || '',
        server: serverName || result.server || ''
      });
      render();
    }

    function trackAll(results, serverName) {
      (results || []).forEach(function (item) {
        add(item, serverName);
      });
      render();
    }

    function stopAll() {
      return global.RtApi.userTestStop().then(function (res) {
        var stopped = (res && res.stopped) || 0;
        active = [];
        render();
        UI.toast('已停止账号认证测试（Accounting-Stop × ' + stopped + '）', 'success');
        return res;
      }, function (error) {
        UI.toast('停止失败：' + (error && error.message ? error.message : error), 'error');
        throw error;
      });
    }

    function clear() {
      active = [];
      render();
    }

    return {
      add: add,
      trackAll: trackAll,
      stopAll: stopAll,
      clear: clear,
      count: function () { return active.length; }
    };
  })();

  global.RtUserTest = UserTest;

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
    // 页面级心跳：测试是否继续，只取决于前端是否仍停在测试页面（需求5）。
    // 离开测试页面即通知后端立即中断测试；窗口切到后台不算离开。
    syncPageHeartbeat(page);
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
      // 页面渲染完成后再补一轮兜底命名，确保首屏元素全部具备 id
      nameElements(container);
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
    // 先给静态外壳（侧栏、导航、页头）补齐 id，再监听后续动态插入的元素
    nameElements(document.body);
    watchNewElements();

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
        if (info.software_version) {
          global.RtDebug.setJsVersion(info.software_version);
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
