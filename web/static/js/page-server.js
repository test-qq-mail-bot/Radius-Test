/* RADIUS Server 页面：Server 配置与连通性测试。
 *
 * 字段名称固定使用（项目书 12）：
 *   authentication_port / accounting_port / nas_ip_address
 */
(function (global) {
  'use strict';

  var PROTOCOLS = ['pap', 'chap', 'mschap', 'mschapv2', 'eap-md5'];

  function field(label, control, hint, rules) {
    var box = document.createElement('div');
    box.className = 'app-field';
    if (rules && rules.length) {
      box._validateSchema = { rules: rules, label: label };
    }
    var labelNode = document.createElement('label');
    labelNode.className = 'app-field-label';
    labelNode.textContent = label;
    box.appendChild(labelNode);
    box.appendChild(control);
    if (hint) {
      var hintNode = document.createElement('span');
      hintNode.className = 'app-field-hint';
      hintNode.textContent = hint;
      box.appendChild(hintNode);
    }
    return box;
  }

  function input(name, value, type, autocomplete, id) {
    var element = document.createElement('input');
    element.className = 'app-field-input';
    element.name = name;
    element.type = type || 'text';
    element.value = value === undefined || value === null ? '' : String(value);
    if (id) { element.id = id; }
    if (autocomplete) {
      element.setAttribute('autocomplete', autocomplete);
    }
    return element;
  }

  function select(name, options, value, id) {
    var element = document.createElement('select');
    element.className = 'app-field-select';
    element.name = name;
    if (id) { element.id = id; }
    options.forEach(function (option) {
      var node = document.createElement('option');
      node.value = option;
      node.textContent = option;
      if (option === value) {
        node.selected = true;
      }
      element.appendChild(node);
    });
    return element;
  }

  function readForm(form) {
    var data = {};
    Array.prototype.forEach.call(form.elements, function (element) {
      if (!element.name) {
        return;
      }
      if (element.type === 'checkbox') {
        data[element.name] = element.checked;
      } else if (element.name === 'authentication_port' || element.name === 'accounting_port' || element.name === 'accounting_interval') {
        data[element.name] = parseInt(element.value, 10) || 0;
      } else if (element.name === 'timeout') {
        data[element.name] = parseFloat(element.value);
      } else if (element.name === 'retry_count') {
        data[element.name] = parseInt(element.value, 10);
      } else {
        data[element.name] = element.value;
      }
    });
    return data;
  }

  function safeId(s) {
    return String(s == null ? '' : s).replace(/[^A-Za-z0-9_-]/g, '_') || 'x';
  }
  var _uidSeq = {};
  function uid(base) {
    base = String(base).replace(/[^A-Za-z0-9_-]/g, '_');
    if (!base || /^[0-9]/.test(base)) base = 'e' + base;
    var n = 1, id = base;
    while (document.getElementById(id)) { id = base + '-' + (++n); }
    return id;
  }

  var Page = {
    title: 'RADIUS Server',
    desc: 'Server 配置与连通性测试',
    render: function (container) {
      var formCard = global.RtUI.card('新增 RADIUS Server');
      formCard.element.id = uid('app-server-form-card');
      var form = document.createElement('form');
      form.className = 'app-form';
      form.id = uid('app-server-form');
      form.setAttribute('autocomplete', 'off');
      var row1 = document.createElement('div');
      row1.className = 'app-form-row';
      row1.id = uid('app-server-row-1');
      row1.appendChild(field('名称', input('name', '', 'text', 'off', 'app-server-name'), null, [{ type: 'required' }]));
      row1.appendChild(field('服务器地址', input('server_address', '', 'text', 'off', 'app-server-address'), null, [{ type: 'host' }]));
      row1.appendChild(field('共享密钥', input('shared_secret', '', 'text', 'new-password', 'app-server-secret'), null, [{ type: 'required' }]));
      form.appendChild(row1);

      var row2 = document.createElement('div');
      row2.className = 'app-form-row';
      row2.id = uid('app-server-row-2');
      row2.appendChild(field('认证端口', input('authentication_port', 1812, 'number', null, 'app-server-auth-port'),
        '默认 1812', [{ type: 'port' }]));
      row2.appendChild(field('RADIUS 认证服务器', input('authentication_server_address', '', 'text', 'off', 'app-server-auth-server'),
        '必填；认证报文发往的服务器地址', [{ type: 'host' }]));
      row2.appendChild(field('认证密钥', input('authentication_secret', '', 'text', 'new-password', 'app-server-auth-secret'),
        '必填；与认证服务器约定', [{ type: 'required' }]));
      form.appendChild(row2);

      var row3 = document.createElement('div');
      row3.className = 'app-form-row';
      row3.id = uid('app-server-row-3');
      row3.appendChild(field('计费端口', input('accounting_port', 1813, 'number', null, 'app-server-acct-port'),
        '默认 1813', [{ type: 'port' }]));
      row3.appendChild(field('RADIUS 计费服务器', input('accounting_server_address', '', 'text', 'off', 'app-server-acct-server'),
        '必填；计费报文发往的服务器地址', [{ type: 'host' }]));
      row3.appendChild(field('计费密钥', input('accounting_secret', '', 'text', 'new-password', 'app-server-acct-secret'),
        '必填；与计费服务器约定', [{ type: 'required' }]));
      row3.appendChild(field('计费间隔（秒）', input('accounting_interval', 0, 'number', null, 'app-server-acct-interval'),
        '0 = 不发送 Interim-Update；>0 按间隔发送', [{ type: 'integer', min: 0 }]));
      form.appendChild(row3);

      var row4 = document.createElement('div');
      row4.className = 'app-form-row';
      row4.id = uid('app-server-row-4');
      row4.appendChild(field('NAS IP 地址', input('nas_ip_address', '', 'text', 'off', 'app-server-nas'),
        '可为空，但非空时必须是 IP 或域名', [{ type: 'host', optional: true }]));
      row4.appendChild(field('超时时间（秒）', input('timeout', 5, 'number', null, 'app-server-timeout'),
        '0.1 ~ 120', [{ type: 'positiveNumber', min: 0.1, max: 120 }]));
      row4.appendChild(field('重试次数', input('retry_count', 3, 'number', null, 'app-server-retry'),
        '1 ~ 10', [{ type: 'positiveNumber', min: 1, max: 10 }]));
      var enabledBox = document.createElement('div');
      enabledBox.className = 'app-field';
      enabledBox.id = uid('app-server-enabled-field');
      var checkRow = document.createElement('div');
      checkRow.className = 'app-checkbox-row';
      var check = document.createElement('input');
      check.type = 'checkbox';
      check.name = 'enabled';
      check.id = uid('app-server-enabled');
      check.checked = true;
      var checkLabel = document.createElement('span');
      checkLabel.className = 'app-checkbox-label';
      checkLabel.textContent = '启用';
      checkRow.appendChild(check);
      checkRow.appendChild(checkLabel);
      enabledBox.appendChild(checkRow);
      row4.appendChild(enabledBox);
      form.appendChild(row4);

      var row5 = document.createElement('div');
      row5.className = 'app-form-row';
      row5.id = uid('app-server-row-5');
      var sourceAddr = input('source_address', '', 'text', 'off', 'app-server-source');
      var sourceList = document.createElement('datalist');
      sourceList.id = 'app-server-source-addresses';
      sourceAddr.setAttribute('list', sourceList.id);
      row5.appendChild(field('报文源地址', sourceAddr,
        '可留空；指定则 RADIUS 报文从该地址发出（须与目标地址同地址族）',
        [{ type: 'host', optional: true }]));
      row5.appendChild(sourceList);
      form.appendChild(row5);

      global.RtApi.listLocalAddresses().then(function (data) {
        (data.addresses || []).forEach(function (addr) {
          var opt = document.createElement('option');
          opt.value = addr;
          opt.textContent = addr;
          sourceList.appendChild(opt);
        });
      }).catch(function () {});

      var submitRow = document.createElement('div');
      submitRow.className = 'app-form-row';
      var submit = global.RtUI.button('新增', 'primary');
      submit.id = uid('app-server-submit');

      /* 按钮内部节点：loading 结束后 withLoading 会用 innerHTML 重建按钮内容，
         因此不能缓存节点引用，必须每次现取并判空。 */
      function submitTextNode() {
        return submit.querySelector('.app-button-text');
      }

      var cancelEdit = global.RtUI.button('取消', '');
      cancelEdit.id = uid('app-server-cancel');
      cancelEdit.hidden = true;
      cancelEdit.addEventListener('click', function () {
        exitEditMode();
      });

      // 收集所有带校验规则的字段，绑定实时校验
      var validateBoxes = [];
      Array.prototype.forEach.call(form.querySelectorAll('.app-field'), function (box) {
        if (box._validateSchema) {
          global.RtUI.validate.bindField(box, box._validateSchema);
          validateBoxes.push(box);
        }
      });

      submit.addEventListener('click', function (event) {
        // 提交前先校验全部字段
        var result = global.RtUI.validate.validateForm(validateBoxes);
        if (!result.valid) {
          global.RtUI.toast('请检查表单中标红的字段', 'warning');
          if (result.firstInvalid && result.firstInvalid.scrollIntoView) {
            result.firstInvalid.scrollIntoView({ block: 'center' });
          }
          return;
        }
        var payload = readForm(form);
        // 是否需要在按钮 loading 结束后退出编辑态。
        // 注意：withLoading 执行期间按钮内部只有 spinner，此时重置按钮文字会取不到 .app-button-text，
        // 因此退出编辑态必须延后到 withLoading 完成、按钮内容恢复后再执行。
        var pendingExitEdit = false;
        global.RtUI.withLoading(submit, function () {
          if (editingName) {
            return global.RtApi.updateServer(editingName, payload).then(function () {
              global.RtUI.toast('Server 已保存', 'success');
              pendingExitEdit = true;
              return load();
            });
          }
          return global.RtApi.createServer(payload).then(function (data) {
            // 名称是唯一键：同名提交由后端覆盖更新，前端按结果区分提示
            if (data && data.updated) {
              global.RtUI.toast('同名 Server 已存在，已覆盖更新：' + payload.name, 'success');
            } else {
              global.RtUI.toast('Server 已新增：' + payload.name, 'success');
            }
            form.reset();
            // 清掉残留错误样式
            validateBoxes.forEach(function (box) { global.RtUI.validate.clearError(box); });
            return load();
          });
        }, event).then(function () {
          // 按钮已恢复，此时退出编辑态不会再被 innerHTML 还原覆盖
          if (pendingExitEdit) {
            pendingExitEdit = false;
            exitEditMode();
          }
        });
      });
      submitRow.appendChild(submit);
      submitRow.appendChild(cancelEdit);
      form.appendChild(submitRow);
      formCard.body.appendChild(form);
      container.appendChild(formCard.element);

      var editingName = null;
      var formCardTitle = formCard.element.querySelector('.app-card-title');
      formCardTitle.id = uid('app-server-form-title');

      function findField(name) {
        return form.querySelector('[name="' + name + '"]');
      }

      function enterEditMode(server) {
        editingName = server.name;
        var textNode = submitTextNode();
        if (textNode) {
          textNode.textContent = '保存';
        }
        findField('name').value = server.name;
        findField('server_address').value = server.server_address;
        findField('shared_secret').value = server.shared_secret || '';
        findField('authentication_server_address').value = server.authentication_server_address || '';
        findField('authentication_secret').value = server.authentication_secret || '';
        findField('authentication_port').value = server.authentication_port;
        findField('accounting_server_address').value = server.accounting_server_address || '';
        findField('accounting_secret').value = server.accounting_secret || '';
        findField('accounting_port').value = server.accounting_port;
        findField('accounting_interval').value = server.accounting_interval;
        findField('nas_ip_address').value = server.nas_ip_address || '';
        findField('source_address').value = server.source_address || '';
        findField('timeout').value = server.timeout;
        findField('retry_count').value = server.retry_count;
        findField('enabled').checked = !!server.enabled;
        cancelEdit.hidden = false;
        validateBoxes.forEach(function (box) { global.RtUI.validate.clearError(box); });
        formCard.element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }

      function exitEditMode() {
        editingName = null;
        var textNode = submitTextNode();
        if (textNode) {
          textNode.textContent = '新增';
        }
        form.reset();
        findField('authentication_port').value = 1812;
        findField('accounting_port').value = 1813;
        findField('accounting_interval').value = 0;
        findField('timeout').value = 5;
        findField('retry_count').value = 3;
        findField('enabled').checked = true;
        validateBoxes.forEach(function (box) { global.RtUI.validate.clearError(box); });
        cancelEdit.hidden = true;
      }

      var listCard = global.RtUI.card('Server 列表');
      var listHost = document.createElement('div');
      listCard.body.appendChild(listHost);
      container.appendChild(listCard.element);

      function actionButton(text, className, handler) {
        var button = document.createElement('button');
        button.className = 'app-button ' + (className || '');
        button.type = 'button';
        var span = document.createElement('span');
        span.className = 'app-button-text';
        span.textContent = text;
        button.appendChild(span);
        button.addEventListener('click', handler);
        return button;
      }

      function openUserTestModal(server, triggerEvent) {
        var body = document.createElement('div');
        body.className = 'app-form';
        body.id = uid('app-usertest-body');

        var username = input('auth-username', '', 'text', 'off', uid('app-usertest-username'));
        var password = input('auth-password', '', 'text', 'new-password', uid('app-usertest-password'));

        var protoField = document.createElement('div');
        protoField.className = 'app-field';
        var protoLabel = document.createElement('label');
        protoLabel.className = 'app-field-label';
        protoLabel.textContent = '认证协议';
        var protoSelect = select('auth-protocol', PROTOCOLS, server.protocol || 'pap', uid('app-usertest-protocol'));
        protoField.appendChild(protoLabel);
        protoField.appendChild(protoSelect);

        var resultBox = document.createElement('div');
        resultBox.className = 'app-detail-list';
        var resultWrap = document.createElement('div');
        resultWrap.className = 'app-test-result';
        resultWrap.hidden = true;
        var resultTitle = document.createElement('div');
        resultTitle.className = 'app-test-result-title';
        resultTitle.textContent = '测试结果';
        resultWrap.appendChild(resultTitle);
        resultWrap.appendChild(resultBox);

        var testBtn = global.RtUI.button('开始测试', 'primary');
        testBtn.id = uid('app-usertest-submit');
        var cancelBtn = global.RtUI.button('取消', '');
        cancelBtn.id = uid('app-usertest-cancel');
        cancelBtn.addEventListener('click', function () {
          global.RtUI.closeModal();
        });
        testBtn.addEventListener('click', function (event) {
          var protocol = protoSelect.value;
          var user = username.value.trim();
          var pass = password.value;
          if (!user) {
            global.RtUI.toast('请输入用户名', 'warning');
            return;
          }
          global.RtUI.withLoading(testBtn, function () {
            return global.RtApi.testUserAuth(server.name, {
              username: user,
              password: pass,
              protocol: protocol
            }).then(function (r) {
              resultBox.innerHTML = '';
              var radiusText = String(r.radius_result || '-');
              // 按认证结果着色：Accept 绿、Reject 红、无响应/其他 橙
              var tone = 'app-result-warn';
              if (radiusText.indexOf('Accept') >= 0 || radiusText.indexOf('成功') >= 0) {
                tone = 'app-result-ok';
              } else if (radiusText.indexOf('Reject') >= 0 || radiusText.indexOf('拒绝') >= 0) {
                tone = 'app-result-fail';
              }
              [
                ['服务器地址', r.server],
                ['认证端口', r.authentication_port],
                ['账号', user],
                ['认证协议', protocol],
                ['连接结果', r.connect_result],
                ['RADIUS 响应结果', radiusText, tone],
                ['响应时间', r.response_time_ms + ' ms'],
                ['错误原因', r.error || '无']
              ].forEach(function (pair) {
                var item = document.createElement('div');
                item.className = 'app-detail-item';
                var key = document.createElement('span');
                key.className = 'app-detail-key';
                key.textContent = pair[0];
                var value = document.createElement('span');
                value.className = 'app-detail-value' + (pair[2] ? (' ' + pair[2]) : '');
                value.textContent = String(pair[1] === undefined || pair[1] === null ? '-' : pair[1]);
                item.appendChild(key);
                item.appendChild(value);
                resultBox.appendChild(item);
              });
              resultWrap.hidden = false;
            });
          }, event);
        });

        body.appendChild(field('用户名', username, null, [{ type: 'required' }]));
        body.appendChild(field('密码', password, null, [{ type: 'required' }]));
        body.appendChild(protoField);
        body.appendChild(resultWrap);
        global.RtUI.modal('Radius 用户测试 - ' + server.name, [], [cancelBtn, testBtn], body);
      }

      function load() {
        return global.RtApi.listServers().then(function (data) {
          listHost.innerHTML = '';
          var servers = data.servers || [];
          if (servers.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'app-table-empty';
            empty.textContent = '暂无 RADIUS Server';
            listHost.appendChild(empty);
            return;
          }
          servers.forEach(function (server) {
            var card = global.RtUI.card(server.name + (server.enabled ? '' : '（已停用）'));
            card.element.id = uid('app-server-item-' + safeId(server.name));
            var info = document.createElement('div');
            info.className = 'app-detail-list';
            [
              ['服务器地址', server.server_address],
              ['认证服务器', server.authentication_server_address || '-'],
              ['认证端口', server.authentication_port],
              ['认证密钥', server.authentication_secret ? '已设置' : '未设置'],
              ['计费服务器', server.accounting_server_address || '-'],
              ['计费端口', server.accounting_port],
              ['计费密钥', server.accounting_secret ? '已设置' : '未设置'],
              ['计费间隔（秒）', server.accounting_interval],
              ['NAS IP 地址', server.nas_ip_address || '-'],
              ['报文源地址', server.source_address || '-'],
              ['超时时间', server.timeout],
              ['重试次数', server.retry_count],
              ['状态', server.enabled ? '启用' : '停用']
            ].forEach(function (pair) {
              var item = document.createElement('div');
              item.className = 'app-detail-item';
              var key = document.createElement('span');
              key.className = 'app-detail-key';
              key.textContent = pair[0];
              var value = document.createElement('span');
              value.className = 'app-detail-value';
              value.textContent = String(pair[1]);
              item.appendChild(key);
              item.appendChild(value);
              info.appendChild(item);
            });
            card.body.appendChild(info);

            var actions = document.createElement('div');
            actions.className = 'app-form-row';
            var testButton = actionButton('测试服务器', '',
              function (event) {
                global.RtUI.withLoading(testButton, function () {
                  return global.RtApi.testServer(server.name).then(function (result) {
                    global.RtUI.modal('测试结果 - ' + server.name, [
                      ['服务器地址', result.server],
                      ['认证端口', result.authentication_port],
                      ['计费端口', result.accounting_port],
                      ['连接结果', result.connect_result],
                      ['RADIUS 响应结果', result.radius_result],
                      ['响应时间', result.response_time_ms + ' ms'],
                      ['错误原因', result.error || '无']
                    ]);
                  });
                }, event);
              });
            testButton.id = uid('app-server-test-' + safeId(server.name));
            var userTestButton = actionButton('Radius 用户测试', '',
              function (event) {
                openUserTestModal(server, event);
              });
            userTestButton.id = uid('app-server-usertest-' + safeId(server.name));
            var editButton = actionButton('修改', '',
              function (event) {
                enterEditMode(server);
              });
            editButton.id = uid('app-server-edit-' + safeId(server.name));
            var deleteButton = actionButton('删除', 'app-button-danger',
              function (event) {
                global.RtUI.confirm('删除 Server', '确认删除 Server「' + server.name + '」？')
                  .then(function (confirmed) {
                    if (!confirmed) {
                      return null;
                    }
                    return global.RtApi.deleteServer(server.name).then(function () {
                      global.RtUI.toast('Server 已删除', 'success');
                      return load();
                    });
                  });
              });
            deleteButton.id = uid('app-server-delete-' + safeId(server.name));
            actions.appendChild(editButton);
            actions.appendChild(testButton);
            actions.appendChild(userTestButton);
            actions.appendChild(deleteButton);
            card.body.appendChild(actions);
            listHost.appendChild(card.element);
          });
        });
      }

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.server = Page;
})(window);
