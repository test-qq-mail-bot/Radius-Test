/* 系统配置页面：软件配置。
 *
 * 说明：
 *   1. 只能修改默认配置中已定义的参数；
 *   2. 保存后需重启程序才能生效；
 *   3. 关于页面已按要求删除，软件名称与版本在本页展示。
 */
(function (global) {
  'use strict';

  var Page = {
    title: '系统配置',
    desc: '软件运行参数与关于信息',
    render: function (container) {
      var controls = {};

      function box(label, control, hint, rules) {
        var wrapper = document.createElement('div');
        wrapper.className = 'app-field';
        if (rules && rules.length) {
          wrapper._validateSchema = { rules: rules, label: label };
        }
        var l = document.createElement('label');
        l.className = 'app-field-label';
        l.textContent = label;
        wrapper.appendChild(l);
        wrapper.appendChild(control);
        if (hint) {
          var h = document.createElement('span');
          h.className = 'app-field-hint';
          h.textContent = hint;
          wrapper.appendChild(h);
        }
        return wrapper;
      }

      function textInput(className, type) {
        var element = document.createElement('input');
        element.className = 'app-field-input ' + className;
        element.type = type || 'text';
        return element;
      }

      var webCard = global.RtUI.card('Web 服务');
      var webForm = document.createElement('div');
      webForm.className = 'app-form';
      var webRow1 = document.createElement('div');
      webRow1.className = 'app-form-row';
      controls.hosts = textInput('app-config-hosts-input');
      webRow1.appendChild(box('监听地址', controls.hosts, '多个地址用英文逗号分隔',
        [{ type: 'required' }]));
      controls.port = textInput('app-config-port-input', 'number');
      webRow1.appendChild(box('监听端口', controls.port, '留空则在 50000~60000 内随机选择',
        [{ type: 'port', optional: true }]));
      webForm.appendChild(webRow1);
      var httpsRow = document.createElement('div');
      httpsRow.className = 'app-checkbox-row';
      controls.https = document.createElement('input');
      controls.https.type = 'checkbox';
      controls.https.className = 'app-config-https-checkbox';
      var httpsLabel = document.createElement('span');
      httpsLabel.className = 'app-checkbox-label';
      httpsLabel.textContent = '启用 HTTPS';
      httpsRow.appendChild(controls.https);
      httpsRow.appendChild(httpsLabel);
      webForm.appendChild(httpsRow);
      webCard.body.appendChild(webForm);
      container.appendChild(webCard.element);

      var logCard = global.RtUI.card('日志');
      var logForm = document.createElement('div');
      logForm.className = 'app-form';
      var logRow = document.createElement('div');
      logRow.className = 'app-form-row';
      controls.logLevel = document.createElement('select');
      controls.logLevel.className = 'app-field-select app-config-loglevel-select';
      ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].forEach(function (level) {
        var option = document.createElement('option');
        option.value = level;
        option.textContent = level;
        controls.logLevel.appendChild(option);
      });
      logRow.appendChild(box('日志等级', controls.logLevel, 'DEBUG 时浏览器控制台输出前端 Debug 信息'));
      logForm.appendChild(logRow);
      logCard.body.appendChild(logForm);
      container.appendChild(logCard.element);

      var testCard = global.RtUI.card('测试参数');
      var testForm = document.createElement('div');
      testForm.className = 'app-form';
      var testRow1 = document.createElement('div');
      testRow1.className = 'app-form-row';
      controls.rate = textInput('app-config-rate-input', 'number');
      testRow1.appendChild(box('测试速率（次/秒）', controls.rate, null,
        [{ type: 'positiveNumber', min: 0.1, max: 10000 }]));
      controls.concurrency = textInput('app-config-concurrency-input', 'number');
      testRow1.appendChild(box('最大并发', controls.concurrency, null,
        [{ type: 'positiveNumber', min: 1, max: 65535 }]));
      controls.timeout = textInput('app-config-timeout-input', 'number');
      testRow1.appendChild(box('请求超时（秒）', controls.timeout, null,
        [{ type: 'positiveNumber', min: 0.1, max: 120 }]));
      controls.retry = textInput('app-config-retry-input', 'number');
      testRow1.appendChild(box('重试次数', controls.retry, null,
        [{ type: 'positiveNumber', min: 1, max: 10 }]));
      testForm.appendChild(testRow1);
      var testRow2 = document.createElement('div');
      testRow2.className = 'app-form-row';
      controls.interim = textInput('app-config-interim-input', 'number');
      testRow2.appendChild(box('Interim-Update 间隔（秒）', controls.interim,
        '0 表示不发送；默认 60', [{ type: 'integer', min: 0, max: 3600 }]));
      controls.interimFail = textInput('app-config-interimfail-input', 'number');
      testRow2.appendChild(box('掉线判定连续失败次数', controls.interimFail,
        '默认 3；判定条件为 60 秒 × 3 次 = 180 秒', [{ type: 'integer', min: 1, max: 10 }]));
      testForm.appendChild(testRow2);
      testCard.body.appendChild(testForm);
      container.appendChild(testCard.element);

      var storageCard = global.RtUI.card('数据存储');
      var storageRow = document.createElement('div');
      storageRow.className = 'app-checkbox-row';
      controls.savePackets = document.createElement('input');
      controls.savePackets.type = 'checkbox';
      controls.savePackets.className = 'app-config-savepackets-checkbox';
      var saveLabel = document.createElement('span');
      saveLabel.className = 'app-checkbox-label';
      saveLabel.textContent = '保存 RADIUS 报文';
      storageRow.appendChild(controls.savePackets);
      storageRow.appendChild(saveLabel);
      var storageHint = document.createElement('div');
      storageHint.className = 'app-field-hint';
      storageHint.textContent = '关闭时只保存认证状态，不保存 RADIUS 报文；'
        + '高并发测试建议保持关闭。';
      storageCard.body.appendChild(storageRow);
      storageCard.body.appendChild(storageHint);
      container.appendChild(storageCard.element);

      var radiusCard = global.RtUI.card('RADIUS 协议');
      var radiusForm = document.createElement('div');
      radiusForm.className = 'app-form';
      var radiusRow = document.createElement('div');
      radiusRow.className = 'app-form-row';
      controls.peerBytes = document.createElement('select');
      controls.peerBytes.className = 'app-field-select app-config-peerbytes-select';
      [['8', '8 字节（pppd 等参考客户端实现，默认）'], ['16', '16 字节（RFC 2759 伪代码）']]
        .forEach(function (pair) {
          var option = document.createElement('option');
          option.value = pair[0];
          option.textContent = pair[1];
          controls.peerBytes.appendChild(option);
        });
      radiusRow.appendChild(box('MS-CHAP v2 Peer-Challenge 字节数', controls.peerBytes,
        '与服务器不一致时可切换为 16 做兼容性验证'));
      radiusForm.appendChild(radiusRow);
      radiusCard.body.appendChild(radiusForm);
      container.appendChild(radiusCard.element);

      var aboutCard = global.RtUI.card('关于');
      var aboutHost = document.createElement('div');
      aboutCard.body.appendChild(aboutHost);
      container.appendChild(aboutCard.element);

      var saveRow = document.createElement('div');
      saveRow.className = 'app-form-row';
      var saveButton = global.RtUI.button('保存配置', 'primary');
      saveButton.classList.add('app-config-save-button');
      saveRow.appendChild(saveButton);
      container.appendChild(saveRow);

      // 收集所有带校验 schema 的 box，绑定实时校验
      var validateBoxes = [];
      Array.prototype.forEach.call(container.querySelectorAll('.app-field'), function (b) {
        if (b._validateSchema) {
          global.RtUI.validate.bindField(b, b._validateSchema);
          validateBoxes.push(b);
        }
      });

      saveButton.addEventListener('click', function (event) {
        var result = global.RtUI.validate.validateForm(validateBoxes);
        if (!result.valid) {
          global.RtUI.toast('请检查表单中标红的字段', 'warning');
          if (result.firstInvalid && result.firstInvalid.scrollIntoView) {
            result.firstInvalid.scrollIntoView({ block: 'center' });
          }
          return;
        }
        var payload = {
          web: {
            hosts: controls.hosts.value.split(',').map(function (item) {
              return item.trim();
            }).filter(function (item) {
              return item;
            }),
            port: controls.port.value ? parseInt(controls.port.value, 10) : null,
            https: controls.https.checked
          },
          log: { level: controls.logLevel.value },
          test: {
            rate: parseFloat(controls.rate.value) || 10,
            max_concurrency: parseInt(controls.concurrency.value, 10) || 10000,
            timeout: parseFloat(controls.timeout.value) || 5,
            retry_count: parseInt(controls.retry.value, 10) || 3,
            interim_interval: parseInt(controls.interim.value, 10) || 0,
            interim_max_fail: parseInt(controls.interimFail.value, 10) || 3
          },
          storage: { save_packets: controls.savePackets.checked },
          radius: { mschap_peer_challenge_bytes: parseInt(controls.peerBytes.value, 10) || 8 }
        };
        global.RtUI.withLoading(saveButton, function () {
          return global.RtApi.saveConfig(payload).then(function () {
            global.RtUI.toast('配置已保存，请重启程序后生效', 'success');
            // 提交成功后清掉残留错误
            validateBoxes.forEach(function (b) { global.RtUI.validate.clearError(b); });
            return load().then(function () {
              // 日志等级可能已实时变更，刷新前端 Debug 开关
              return global.RtApi.getConfig().then(function (cfg) {
                var lvl = ((cfg.config || {}).log || {}).level || 'INFO';
                if (global.RtDebug) {
                  global.RtDebug.setEnabled(String(lvl).toUpperCase() === 'DEBUG');
                }
              });
            });
          });
        }, event);
      });

      function renderAbout(info) {
        aboutHost.innerHTML = '';
        var list = document.createElement('div');
        list.className = 'app-detail-list';
        [
          ['软件名称', info.software_name],
          ['软件版本', info.software_version],
          ['软件说明', info.software_description],
          ['前端版本', info.frontend_version],
          ['Python 版本', info.python_version],
          ['操作系统', info.platform],
          ['数据目录', info.data_dir],
          ['日志目录', info.log_dir],
          ['HTTPS', info.https_enabled ? '已启用' : '已关闭'],
          ['证书指纹', info.certificate_fingerprint || '-'],
          ['监听地址', (info.listen && info.listen.hosts || []).join('、') || '-'],
          ['监听端口', info.listen && info.listen.port]
        ].forEach(function (pair) {
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
        aboutHost.appendChild(list);
      }

      function load() {
        return Promise.all([
          global.RtApi.getConfig(),
          global.RtApi.systemInfo()
        ]).then(function (results) {
          var config = results[0].config || {};
          var info = results[1] || {};
          var web = config.web || {};
          var log = config.log || {};
          var test = config.test || {};
          var storage = config.storage || {};
          var radius = config.radius || {};

          controls.hosts.value = (web.hosts || []).join(',');
          controls.port.value = web.port ? String(web.port) : '';
          controls.https.checked = !!web.https;
          controls.logLevel.value = log.level || 'INFO';
          controls.rate.value = String(test.rate || 10);
          controls.concurrency.value = String(test.max_concurrency || 10000);
          controls.timeout.value = String(test.timeout || 5);
          controls.retry.value = String(test.retry_count || 3);
          controls.interim.value = String(test.interim_interval || 0);
          controls.interimFail.value = String(test.interim_max_fail || 3);
          controls.savePackets.checked = !!storage.save_packets;
          controls.peerBytes.value = String(radius.mschap_peer_challenge_bytes || 8);
          renderAbout(info);
        });
      }

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.config = Page;
})(window);
