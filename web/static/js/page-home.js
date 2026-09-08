/* 首页：软件状态与测试概况。 */
(function (global) {
  'use strict';

  function metric(label, value, unit) {
    var box = document.createElement('div');
    box.className = 'app-metric';
    var labelNode = document.createElement('div');
    labelNode.className = 'app-metric-label';
    labelNode.textContent = label;
    var valueNode = document.createElement('div');
    valueNode.className = 'app-metric-value';
    valueNode.textContent = value;
    if (unit) {
      var unitNode = document.createElement('span');
      unitNode.className = 'app-metric-unit';
      unitNode.textContent = unit;
      valueNode.appendChild(unitNode);
    }
    box.appendChild(labelNode);
    box.appendChild(valueNode);
    return box;
  }

  function infoCard(title, pairs) {
    var card = global.RtUI.card(title);
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
      value.textContent = pair[1] === undefined || pair[1] === null ? '-' : String(pair[1]);
      item.appendChild(key);
      item.appendChild(value);
      list.appendChild(item);
    });
    card.body.appendChild(list);
    return card.element;
  }

      var Page = {
    title: '首页',
    desc: '软件状态及测试概况',
    render: function (container) {
      var grid = document.createElement('div');
      grid.className = 'app-grid app-grid-4';
      container.appendChild(grid);

      var summaryCard = global.RtUI.card('测试概况');
      var summaryBody = document.createElement('div');
      summaryBody.className = 'app-grid app-grid-3';
      summaryCard.body.appendChild(summaryBody);
      container.appendChild(summaryCard.element);

      var envCardHost = document.createElement('div');
      container.appendChild(envCardHost);

      function renderEmpty(host) {
        host.innerHTML = '';
        var empty = document.createElement('div');
        empty.className = 'app-empty';
        var icon = document.createElement('img');
        icon.className = 'app-empty-icon';
        icon.src = '/static/svg/status-info.svg';
        icon.alt = '';
        var title = document.createElement('div');
        title.className = 'app-empty-title';
        title.textContent = '暂无进行中的测试';
        var hint = document.createElement('div');
        hint.className = 'app-empty-hint';
        hint.textContent = '前往「性能测试」页面发起一次 RADIUS 认证测试';
        var btn = global.RtUI.button('前往性能测试', 'primary');
        btn.addEventListener('click', function () {
          location.hash = '#/perf';
        });
        empty.appendChild(icon);
        empty.appendChild(title);
        empty.appendChild(hint);
        empty.appendChild(btn);
        host.appendChild(empty);
      }

      function renderSummary(session) {
        summaryBody.innerHTML = '';
        var data = session || {};
        summaryBody.appendChild(metric('当前在线数', data.online || 0, '个'));
        summaryBody.appendChild(metric('总请求数', data.total || 0, '次'));
        summaryBody.appendChild(metric('成功率', data.success_rate || 0, '%'));
        summaryBody.appendChild(metric('成功数', data.success || 0, '次'));
        summaryBody.appendChild(metric('失败数', data.failed || 0, '次'));
        summaryBody.appendChild(metric('超时数', data.timeout || 0, '次'));
        summaryBody.appendChild(metric('最大响应时间', data.max_response_time || 0, 'ms'));
        summaryBody.appendChild(metric('最小响应时间', data.min_response_time || 0, 'ms'));
        summaryBody.appendChild(metric('运行时长', data.elapsed_seconds || 0, '秒'));
      }

      function load() {
        return Promise.all([
          global.RtApi.systemInfo(),
          global.RtApi.systemStats()
        ]).then(function (results) {
          var info = results[0] || {};
          var stats = results[1] || {};
          grid.innerHTML = '';
          grid.appendChild(metric('软件版本', info.software_version || '-', ''));
          var statusVal = stats.has_session ? '测试进行中' : '空闲';
          var statusNode = metric('运行状态', statusVal, '');
          if (stats.has_session) {
            statusNode.querySelector('.app-metric-value').classList.add('is-success');
          }
          grid.appendChild(statusNode);
          grid.appendChild(metric('HTTPS', info.https_enabled ? '已启用' : '已关闭', ''));
          var wsCount = stats.websocket_connections || 0;
          grid.appendChild(metric('WebSocket 连接', wsCount, '个'));

          if (stats.has_session) {
            summaryBody.className = 'app-grid app-grid-3';
            renderSummary(stats.session);
          } else {
            summaryBody.className = '';
            renderEmpty(summaryBody);
          }

          var db = stats.database || {};
          var pool = stats.socket_pool || {};
          envCardHost.innerHTML = '';
          envCardHost.appendChild(infoCard('运行环境', [
            ['Python 版本', info.python_version],
            ['操作系统', info.platform],
            ['监听地址', (info.listen && info.listen.hosts || []).join('、') || '-'],
            ['监听端口', info.listen && info.listen.port],
            ['数据目录', info.data_dir],
            ['日志目录', info.log_dir],
            ['证书指纹', info.certificate_fingerprint || '-'],
            ['Socket 池槽位', pool.ipv4 ? pool.ipv4.slots : 0],
            ['Socket 池容量', pool.ipv4 ? pool.ipv4.capacity : 0],
            ['待写入任务', db.pending],
            ['已写入任务', db.written]
          ]));
        });
      }

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.home = Page;
})(window);
