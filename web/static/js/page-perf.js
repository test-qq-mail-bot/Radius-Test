/* 性能测试页面：单用户/多用户测试。
 *
 * 安全机制（项目书 26）：
 *   1. 点击开始测试后必须弹出二次确认，展示目标、用户、速率、并发、协议；
 *   2. 测试过程中始终提供停止按钮；
 *   3. 前端失联后端会在约 6 秒后自动终止测试。
 */
(function (global) {
  'use strict';

  var state = {
    servers: [],
    users: [],
    config: null
  };

  function metricNode(label, value, unit) {
    var box = document.createElement('div');
    box.className = 'app-metric';
    box.id = global.uid('app-perf-metric-' + String(label).replace(/[^A-Za-z0-9_-]/g, '_'));
    var l = document.createElement('div');
    l.className = 'app-metric-label';
    l.textContent = label;
    var v = document.createElement('div');
    v.className = 'app-metric-value';
    v.textContent = value;
    if (unit) {
      var u = document.createElement('span');
      u.className = 'app-metric-unit';
      u.textContent = unit;
      v.appendChild(u);
    }
    box.appendChild(l);
    box.appendChild(v);
    return box;
  }

  function inputRow(label, control, hint) {
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

  var Page = {
    title: '性能测试',
    desc: '模拟 dot1x 用户登录，发起认证与计费压测',
    render: function (container) {
      var controls = {};
      var setupCard = global.RtUI.card('测试参数');
      setupCard.element.id = global.uid('app-perf-setup-card');
      var form = document.createElement('div');
      form.className = 'app-form';
      form.id = global.uid('app-perf-form');

      var row1 = document.createElement('div');
      row1.className = 'app-form-row';
      row1.id = global.uid('app-perf-row-1');
      controls.server = document.createElement('select');
      controls.server.className = 'app-field-select app-perf-server-select';
      controls.server.id = global.uid('app-perf-server');
      row1.appendChild(inputRow('目标 RADIUS Server', controls.server));
      controls.protocol = document.createElement('select');
      controls.protocol.className = 'app-field-select app-perf-protocol-select';
      controls.protocol.id = global.uid('app-perf-protocol');
      ['pap', 'chap', 'mschap', 'mschapv2', 'eap-md5'].forEach(function (item) {
        var option = document.createElement('option');
        option.value = item;
        option.textContent = item;
        controls.protocol.appendChild(option);
      });
      row1.appendChild(inputRow('测试协议', controls.protocol));
      form.appendChild(row1);

      var row2 = document.createElement('div');
      row2.className = 'app-form-row';
      row2.id = global.uid('app-perf-row-2');
      controls.rate = document.createElement('input');
      controls.rate.className = 'app-field-input app-perf-rate-input';
      controls.rate.id = global.uid('app-perf-rate');
      controls.rate.type = 'number';
      controls.rate.value = '10';
      row2.appendChild(inputRow('测试速率（次/秒）', controls.rate, '每秒发起的完整登录数'));
      controls.concurrency = document.createElement('input');
      controls.concurrency.className = 'app-field-input app-perf-concurrency-input';
      controls.concurrency.id = global.uid('app-perf-concurrency');
      controls.concurrency.type = 'number';
      controls.concurrency.value = '10000';
      row2.appendChild(inputRow('最大并发', controls.concurrency, '同时在途任务上限'));
      controls.onlineCriteria = document.createElement('select');
      controls.onlineCriteria.className = 'app-field-select app-perf-onlinecriteria-select';
      controls.onlineCriteria.id = global.uid('app-perf-online-criteria');
      [
        ['accounting', '计费上线成功（默认）'],
        ['auth', '认证成功']
      ].forEach(function (item) {
        var option = document.createElement('option');
        option.value = item[0];
        option.textContent = item[1];
        controls.onlineCriteria.appendChild(option);
      });
      row2.appendChild(inputRow('在线判定依据', controls.onlineCriteria,
        '服务端不支撑计费时可选「认证成功」，计费失败不再影响在线统计'));
      form.appendChild(row2);

      var row3 = document.createElement('div');
      row3.className = 'app-form-row';
      row3.id = global.uid('app-perf-row-3');
      controls.savePackets = document.createElement('input');
      controls.savePackets.type = 'checkbox';
      controls.savePackets.id = global.uid('app-perf-save-packets');
      controls.savePackets.className = 'app-perf-savepackets-checkbox';
      var saveRow = document.createElement('div');
      saveRow.className = 'app-checkbox-row';
      var saveLabel = document.createElement('span');
      saveLabel.className = 'app-checkbox-label';
      saveLabel.textContent = '保存 RADIUS 报文';
      saveRow.appendChild(controls.savePackets);
      saveRow.appendChild(saveLabel);
      var saveBox = document.createElement('div');
      saveBox.className = 'app-field';
      var saveHint = document.createElement('span');
      saveHint.className = 'app-field-hint';
      saveHint.textContent = '关闭时只保存认证状态';
      saveBox.appendChild(saveRow);
      saveBox.appendChild(saveHint);
      row3.appendChild(saveBox);

      controls.accounting = document.createElement('input');
      controls.accounting.type = 'checkbox';
      controls.accounting.id = global.uid('app-perf-accounting');
      controls.accounting.className = 'app-perf-accounting-checkbox';
      controls.accounting.checked = true;
      var acctRow = document.createElement('div');
      acctRow.className = 'app-checkbox-row';
      var acctLabel = document.createElement('span');
      acctLabel.className = 'app-checkbox-label';
      acctLabel.textContent = '启用计费（Accounting）';
      acctRow.appendChild(controls.accounting);
      acctRow.appendChild(acctLabel);
      var acctBox = document.createElement('div');
      acctBox.className = 'app-field';
      var acctHint = document.createElement('span');
      acctHint.className = 'app-field-hint';
      acctHint.textContent = '关闭后不发送计费报文；在线判定依据选「认证成功」时仍统计在线数';
      acctBox.appendChild(acctRow);
      acctBox.appendChild(acctHint);
      row3.appendChild(acctBox);
      form.appendChild(row3);

      var userBox = document.createElement('div');
      userBox.className = 'app-field';
      userBox.id = global.uid('app-perf-user-box');
      var userLabel = document.createElement('label');
      userLabel.className = 'app-field-label';
      userLabel.textContent = '测试用户（可多选，不选表示全部用户）';
      userBox.appendChild(userLabel);

      var userActions = document.createElement('div');
      userActions.className = 'app-user-list-actions';
      userActions.id = global.uid('app-perf-user-actions');
      var selectAllBtn = global.RtUI.button('全选', 'ghost', 'sm');
      selectAllBtn.id = global.uid('app-perf-select-all');
      var selectNoneBtn = global.RtUI.button('全不选', 'ghost', 'sm');
      selectNoneBtn.id = global.uid('app-perf-select-none');
      userActions.appendChild(selectAllBtn);
      userActions.appendChild(selectNoneBtn);
      userBox.appendChild(userActions);

      controls.users = document.createElement('div');
      controls.users.className = 'app-user-list app-perf-user-list';
      controls.users.id = global.uid('app-perf-user-list');
      userBox.appendChild(controls.users);
      form.appendChild(userBox);

      selectAllBtn.addEventListener('click', function () {
        Array.prototype.forEach.call(
          controls.users.querySelectorAll('input[type="checkbox"]:not(:disabled)'),
          function (cb) { cb.checked = true; });
      });
      selectNoneBtn.addEventListener('click', function () {
        Array.prototype.forEach.call(
          controls.users.querySelectorAll('input[type="checkbox"]'),
          function (cb) { cb.checked = false; });
      });

      var buttonRow = document.createElement('div');
      buttonRow.className = 'app-form-row';
      buttonRow.id = global.uid('app-perf-button-row');
      var startButton = global.RtUI.button('开始测试', 'primary');
      startButton.classList.add('app-perf-start-button');
      startButton.id = global.uid('app-perf-start');
      var stopButton = global.RtUI.button('停止测试', 'danger');
      stopButton.classList.add('app-perf-stop-button');
      stopButton.id = global.uid('app-perf-stop');
      stopButton.disabled = true;
      buttonRow.appendChild(startButton);
      buttonRow.appendChild(stopButton);
      form.appendChild(buttonRow);

      setupCard.body.appendChild(form);
      container.appendChild(setupCard.element);

      var metricsCard = global.RtUI.card('实时指标');
      metricsCard.element.id = global.uid('app-perf-metrics-card');
      var metricsHost = document.createElement('div');
      metricsHost.className = 'app-grid app-grid-4';
      metricsHost.id = global.uid('app-perf-metrics-host');
      metricsCard.body.appendChild(metricsHost);
      container.appendChild(metricsCard.element);

      function selectedUsers() {
        return Array.prototype.filter.call(
          controls.users.querySelectorAll('input[type="checkbox"]'),
          function (cb) { return cb.checked; }
        ).map(function (cb) { return cb.value; });
      }

      function renderMetrics(data) {
        metricsHost.innerHTML = '';
        var d = data || {};
        metricsHost.appendChild(metricNode('测试状态', d.status_text || '空闲', ''));
        metricsHost.appendChild(metricNode('当前在线数', d.online || 0, '个'));
        metricsHost.appendChild(metricNode('总请求数', d.total || 0, '次'));
        metricsHost.appendChild(metricNode('成功率', d.success_rate || 0, '%'));
        metricsHost.appendChild(metricNode('成功数', d.success || 0, '次'));
        metricsHost.appendChild(metricNode('失败数', d.failed || 0, '次'));
        metricsHost.appendChild(metricNode('超时数', d.timeout || 0, '次'));
        metricsHost.appendChild(metricNode('取消数', d.cancelled || 0, '次'));
        metricsHost.appendChild(metricNode('最大响应时间', d.max_response_time || 0, 'ms'));
        metricsHost.appendChild(metricNode('最小响应时间', d.min_response_time || 0, 'ms'));
        metricsHost.appendChild(metricNode('运行时长', d.elapsed_seconds || 0, '秒'));
        metricsHost.appendChild(metricNode('在途任务', (d.concurrency && d.concurrency.running) || 0, '个'));
      }

      var handlerRegistered = false;

      function registerHandler() {
        if (handlerRegistered) {
          return;
        }
        handlerRegistered = true;
        global.RtWs.on('test_progress', function (data) {
          renderMetrics(data);
          startButton.disabled = true;
          stopButton.disabled = false;
          if (data && data.status && data.status !== 'RUNNING') {
            startButton.disabled = false;
            stopButton.disabled = true;
            if (data.stop_reason) {
              global.RtUI.toast('测试已停止：' + (data.stop_reason_text || data.stop_reason), 'warning');
            }
          }
        });
      }

      startButton.addEventListener('click', function (event) {
        var users = selectedUsers();
        var payload = {
          server_name: controls.server.value,
          usernames: users,
          protocol: controls.protocol.value,
          rate: parseFloat(controls.rate.value) || 10,
          concurrency: parseInt(controls.concurrency.value, 10) || 10000,
          save_packets: controls.savePackets.checked,
          enable_accounting: controls.accounting.checked,
          online_criteria: controls.onlineCriteria.value
        };
        if (!payload.server_name) {
          global.RtUI.toast('请先选择 RADIUS Server', 'warning');
          return;
        }
        var userText = users.length === 0 ? '全部用户' : (users.join('、') || '');
        global.RtUI.confirm('确认开始测试', '', [
          ['目标 RADIUS Server', payload.server_name],
          ['测试用户', userText],
          ['并发数', payload.concurrency],
          ['测试速率', payload.rate + ' 次/秒'],
          ['测试协议', payload.protocol],
          ['保存报文', payload.save_packets ? '是' : '否'],
          ['启用计费', payload.enable_accounting ? '是' : '否'],
          ['在线判定依据', payload.online_criteria === 'auth' ? '认证成功' : '计费上线成功']
        ]).then(function (confirmed) {
          if (!confirmed) {
            return null;
          }
          return global.RtUI.withLoading(startButton, function () {
            return global.RtApi.startTask(payload).then(function (result) {
              global.RtUI.toast('测试已启动', 'success');
              startButton.disabled = true;
              stopButton.disabled = false;
              renderMetrics(result.session);
            });
          }, event);
        });
      });

      stopButton.addEventListener('click', function (event) {
        global.RtApi.currentTask().then(function (data) {
          if (!data.has_session) {
            global.RtUI.toast('当前没有运行中的测试', 'warning');
            return null;
          }
          return global.RtUI.withLoading(stopButton, function () {
            return global.RtApi.stopTask(data.session.task_id).then(function (result) {
              global.RtUI.toast(result.message || '已终止', 'success');
              startButton.disabled = false;
              stopButton.disabled = true;
              renderMetrics(result.session);
            });
          }, event);
        });
      });

      function load() {
        return Promise.all([
          global.RtApi.listServers(),
          global.RtApi.listUsers(),
          global.RtApi.getConfig(),
          global.RtApi.currentTask()
        ]).then(function (results) {
          state.servers = (results[0].servers || []).filter(function (s) {
            return s.enabled;
          });
          state.users = results[1].users || [];
          state.config = results[2].config || {};

          controls.server.innerHTML = '';
          state.servers.forEach(function (server) {
            var option = document.createElement('option');
            option.value = server.name;
            option.textContent = server.name + ' (' + server.server_address + ')';
            controls.server.appendChild(option);
          });
          if (state.servers.length > 0) {
            controls.protocol.value = state.servers[0].protocol || 'pap';
          }

          controls.users.innerHTML = '';
          if (state.users.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'app-user-list-empty';
            empty.textContent = '暂无用户，请先在「用户管理」中新增';
            controls.users.appendChild(empty);
          }
          state.users.forEach(function (user) {
            var label = document.createElement('label');
            label.className = 'app-user-list-item';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = user.username;
            cb.checked = true;
            var text = document.createElement('span');
            text.textContent = user.username + (user.remark ? ' - ' + user.remark : '');
            label.appendChild(cb);
            label.appendChild(text);
            controls.users.appendChild(label);
          });

          var test = state.config.test || {};
          controls.rate.value = String(test.rate || 10);
          controls.concurrency.value = String(test.max_concurrency || 10000);
          controls.savePackets.checked = !!(state.config.storage || {}).save_packets;

          registerHandler();
          var current = results[3] || {};
          if (current.has_session) {
            renderMetrics(current.session);
            startButton.disabled = current.session.status === 'RUNNING';
            stopButton.disabled = current.session.status !== 'RUNNING';
          } else {
            renderMetrics(null);
            startButton.disabled = false;
            stopButton.disabled = true;
          }
        });
      }

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.perf = Page;
})(window);
