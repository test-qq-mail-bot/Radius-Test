/* 测试结果页面：测试任务及结果查询。
 *
 * 表格行为严格遵循《数据表格需求描述》：
 *   默认用户名升序、每页 10 条、字段排序、字段筛选、
 *   多重筛选联动、筛选状态展示、分页数量切换。
 */
(function (global) {
  'use strict';

  function badge(text, kind) {
    var span = document.createElement('span');
    span.className = 'app-badge app-badge-' + (kind || 'muted');
    span.textContent = text;
    return span;
  }

  function buildQueryFromFilters(filters, excludeField) {
    var parts = [];
    Object.keys(filters || {}).forEach(function (field) {
      if (field === excludeField) {
        return;
      }
      (filters[field] || []).forEach(function (value) {
        parts.push(encodeURIComponent(field) + '=' + encodeURIComponent(value));
      });
    });
    return parts.join('&');
  }

  var Page = {
    title: '测试结果',
    desc: '测试任务及每次测试结果的查询与分析',
    render: function (container) {
      var sessionCard = global.RtUI.card('测试任务');
      var sessionHost = document.createElement('div');
      sessionCard.body.appendChild(sessionHost);
      container.appendChild(sessionCard.element);

      var resultCard = global.RtUI.card('测试结果');
      var tableHost = document.createElement('div');
      resultCard.body.appendChild(tableHost);
      var actions = document.createElement('div');
      actions.className = 'app-form-row';
      var clearButton = document.createElement('button');
      clearButton.className = 'app-button app-button-danger app-result-clear-button';
      clearButton.type = 'button';
      clearButton.textContent = '清空测试数据';
      clearButton.addEventListener('click', function () {
        global.RtUI.confirm('清空数据', '确认清空全部测试结果、报文与属性数据？')
          .then(function (confirmed) {
            if (!confirmed) {
              return null;
            }
            return global.RtApi.clearResults().then(function () {
              global.RtUI.toast('测试数据已清空', 'success');
              return table.reload();
            });
          });
      });
      actions.appendChild(clearButton);
      resultCard.body.appendChild(actions);
      container.appendChild(resultCard.element);

      var table = global.RtTable.create({
        container: tableHost,
        defaultSortField: 'username',
        columns: [
          {
            key: 'username',
            label: '用户名'
          },
          {
            key: 'test_time',
            label: '测试时间'
          },
          {
            key: 'online',
            label: '是否在线',
            render: function (row) {
              return badge(row.online ? '在线' : '离线', row.online ? 'success' : 'muted');
            }
          },
          {
            key: 'success',
            label: '是否测试成功',
            render: function (row) {
              return badge(row.success ? '成功' : '失败', row.success ? 'success' : 'failed');
            }
          },
          {
            key: 'server',
            label: 'RADIUS Server'
          },
          {
            key: 'status',
            label: '测试状态',
            render: function (row) {
              var kind = row.status === 'SUCCESS' ? 'success'
                : (row.status === 'FAILED' ? 'failed' : 'warning');
              return badge(row.status, kind);
            }
          },
          {
            key: 'response_time',
            label: '响应时间',
            render: function (row) {
              return (row.response_time || 0) + ' ms';
            }
          }
        ],
        fetchData: function (query) {
          return global.RtApi.queryResults(query);
        },
        fetchOptions: function (field, otherFilters) {
          var query = 'field=' + encodeURIComponent(field);
          var extra = buildQueryFromFilters(otherFilters);
          if (extra) {
            query += '&' + extra;
          }
          return global.RtApi.resultFilters(query).then(function (data) {
            return (data.filters || {})[field] || [];
          });
        },
        onRowClick: function (row) {
          global.RtApi.resultDetail(row.id).then(function (detail) {
            showDetail(detail);
          });
        }
      });

      function showDetail(detail) {
        var host = document.createElement('div');

        var infoTitle = document.createElement('div');
        infoTitle.className = 'app-detail-title';
        infoTitle.textContent = '测试信息';
        host.appendChild(infoTitle);

        var infoList = document.createElement('div');
        infoList.className = 'app-detail-list';
        var session = detail.session || {};
        [
          ['任务 ID', detail.task_id],
          ['用户名', detail.username],
          ['RADIUS Server', detail.server],
          ['测试时间', detail.test_time],
          ['是否在线', detail.online ? '在线' : '离线'],
          ['是否成功', detail.success ? '成功' : '失败'],
          ['测试状态', detail.status],
          ['响应时间', (detail.response_time || 0) + ' ms'],
          ['错误信息', detail.error || '无'],
          ['任务协议', session.protocol || '-'],
          ['任务并发', session.concurrency || '-'],
          ['任务速率', session.rate || '-']
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
        host.appendChild(infoList);

        var packets = detail.packets || [];
        if (packets.length === 0) {
          var empty = document.createElement('div');
          empty.className = 'app-table-empty';
          empty.textContent = '本次测试未保存 RADIUS 报文（保存报文配置已关闭）';
          host.appendChild(empty);
        }
        packets.forEach(function (packet) {
          var title = document.createElement('div');
          title.className = 'app-detail-title';
          title.textContent = packet.packet_type || '报文';
          host.appendChild(title);

          var attrWrap = document.createElement('div');
          attrWrap.className = 'app-table-wrap';
          var attrTable = document.createElement('table');
          attrTable.className = 'app-table';
          var thead = document.createElement('thead');
          var headRow = document.createElement('tr');
          ['Radius模板', 'Name', 'Name_ZH', 'Type', 'Value'].forEach(function (text) {
            var th = document.createElement('th');
            th.textContent = text;
            headRow.appendChild(th);
          });
          thead.appendChild(headRow);
          var tbody = document.createElement('tbody');
          (packet.attributes || []).forEach(function (attribute) {
            var tr = document.createElement('tr');
            [
              attribute.radius_template,
              attribute.name,
              attribute.name_zh,
              attribute.type,
              attribute.value
            ].forEach(function (value) {
              var td = document.createElement('td');
              td.textContent = value === undefined || value === null ? '' : String(value);
              tr.appendChild(td);
            });
            tbody.appendChild(tr);
          });
          attrTable.appendChild(thead);
          attrTable.appendChild(tbody);
          attrWrap.appendChild(attrTable);
          host.appendChild(attrWrap);
        });

        global.RtUI.modal('测试详情 - ' + detail.username, [], [], host);
      }

      function loadSessions() {
        return global.RtApi.listSessions('page=1&page_size=10').then(function (data) {
          sessionHost.innerHTML = '';
          var rows = data.rows || [];
          if (rows.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'app-table-empty';
            empty.textContent = '暂无符合条件的数据';
            sessionHost.appendChild(empty);
            return;
          }
          var wrap = document.createElement('div');
          wrap.className = 'app-table-wrap';
          var tableEl = document.createElement('table');
          tableEl.className = 'app-table';
          var thead = document.createElement('thead');
          var headRow = document.createElement('tr');
          ['任务 ID', '开始时间', '结束时间', 'Server', '协议', '并发', '速率', '停止原因'].forEach(function (text) {
            var th = document.createElement('th');
            th.textContent = text;
            headRow.appendChild(th);
          });
          thead.appendChild(headRow);
          var tbody = document.createElement('tbody');
          rows.forEach(function (row) {
            var tr = document.createElement('tr');
            var fullId = String(row.task_id || '');
            var shortId = fullId.length > 10 ? fullId.slice(0, 8) + '...' : fullId;
            [
              shortId,
              row.start_time,
              row.end_time,
              row.server,
              row.protocol,
              row.concurrency,
              row.rate,
              row.stop_reason || '-'
            ].forEach(function (value, idx) {
              var td = document.createElement('td');
              if (idx === 0) {
                td.className = 'app-table-cell-mono';
                td.textContent = value;
                td.title = '点击复制：' + fullId;
                td.style.cursor = 'pointer';
                td.addEventListener('click', function () {
                  if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(fullId).then(function () {
                      global.RtUI.toast('已复制任务 ID', 'success');
                    }, function () {
                      global.RtUI.toast('复制失败', 'error');
                    });
                  } else {
                    global.RtUI.toast('当前浏览器不支持剪贴板 API', 'warning');
                  }
                });
              } else {
                td.textContent = value === undefined || value === null ? '' : String(value);
              }
              tr.appendChild(td);
            });
            tbody.appendChild(tr);
          });
          tableEl.appendChild(thead);
          tableEl.appendChild(tbody);
          wrap.appendChild(tableEl);
          sessionHost.appendChild(wrap);
        });
      }

      function load() {
        return Promise.all([loadSessions(), table.reload()]);
      }

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.result = Page;
})(window);
