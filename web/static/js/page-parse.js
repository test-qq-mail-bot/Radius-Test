/* RADIUS 解析页面：查询已保存的 RADIUS 报文解析结果。
 *
 * 说明（用户确认口径）：
 *   本页面用于事后查询数据库中已保存的 RADIUS 报文，
 *   不提供实时抓包能力。
 *   若 save_packets 关闭，则不会有任何报文数据。
 */
(function (global) {
  'use strict';

  var Page = {
    title: 'RADIUS 解析',
    desc: '查询已保存 RADIUS 报文的解析结果与模板匹配结果',
    render: function (container) {
      var hint = document.createElement('div');
      hint.className = 'app-field-hint';
      hint.textContent = '本页查询测试过程中保存的 RADIUS 报文；'
        + '若「保存 RADIUS 报文」配置关闭，则不会有任何数据。';
      container.appendChild(hint);

      var card = global.RtUI.card('报文列表');
      var host = document.createElement('div');
      card.body.appendChild(host);
      container.appendChild(card.element);

      var table = global.RtTable.create({
        container: host,
        defaultSortField: 'id',
        columns: [
          { key: 'id', label: '报文 ID' },
          { key: 'username', label: '用户名' },
          { key: 'server', label: 'RADIUS Server' },
          { key: 'packet_type', label: '报文类型' },
          { key: 'packet_time', label: '报文时间' },
          { key: 'parse_status', label: '解析状态' }
        ],
        fetchData: function (query) {
          return global.RtApi.listPackets(query).then(function (data) {
            return { rows: data.rows || [], total: data.total || 0 };
          });
        },
        onRowClick: function (row) {
          global.RtApi.packetDetail(row.id).then(function (detail) {
            showDetail(detail);
          });
        }
      });

      function showDetail(detail) {
        var hostEl = document.createElement('div');

        var infoTitle = document.createElement('div');
        infoTitle.className = 'app-detail-title';
        infoTitle.textContent = '报文信息';
        hostEl.appendChild(infoTitle);

        var infoList = document.createElement('div');
        infoList.className = 'app-detail-list';
        [
          ['报文 ID', detail.id],
          ['任务 ID', detail.task_id],
          ['用户名', detail.username],
          ['RADIUS Server', detail.server],
          ['报文类型', detail.packet_type],
          ['报文时间', detail.packet_time],
          ['解析状态', detail.parse_status],
          ['解析错误', detail.parse_error || '无']
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
          infoList.appendChild(item);
        });
        hostEl.appendChild(infoList);

        var rawTitle = document.createElement('div');
        rawTitle.className = 'app-detail-title';
        rawTitle.textContent = '原始报文（十六进制）';
        hostEl.appendChild(rawTitle);
        var raw = document.createElement('div');
        raw.className = 'app-code-block';
        raw.textContent = detail.raw_packet || '';
        hostEl.appendChild(raw);

        var attrTitle = document.createElement('div');
        attrTitle.className = 'app-detail-title';
        attrTitle.textContent = '报文解析结果与 Radius 模板匹配结果';
        hostEl.appendChild(attrTitle);

        var wrap = document.createElement('div');
        wrap.className = 'app-table-wrap';
        var tableEl = document.createElement('table');
        tableEl.className = 'app-table';
        var thead = document.createElement('thead');
        var headRow = document.createElement('tr');
        ['Radius模板', 'Name', 'Name_ZH', 'Type', 'Value', 'Vendor-ID', '属性编号'].forEach(function (text) {
          var th = document.createElement('th');
          th.textContent = text;
          headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        var tbody = document.createElement('tbody');
        (detail.attributes || []).forEach(function (attribute) {
          var tr = document.createElement('tr');
          [
            attribute.radius_template,
            attribute.name,
            attribute.name_zh,
            attribute.type,
            attribute.value,
            attribute.vendor_id === null || attribute.vendor_id === undefined
              ? '-' : attribute.vendor_id,
            attribute.attribute_id
          ].forEach(function (value) {
            var td = document.createElement('td');
            td.textContent = value === undefined || value === null ? '' : String(value);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        tableEl.appendChild(thead);
        tableEl.appendChild(tbody);
        wrap.appendChild(tableEl);
        hostEl.appendChild(wrap);

        global.RtUI.modal('报文详情 #' + detail.id, [], [], hostEl);
      }

      function load() {
        return table.reload();
      }

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.parse = Page;
})(window);
