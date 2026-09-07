/* 用户管理页面：CSV 用户管理、导入、导出、批量测试/删除。
 *
 * 表格严格遵循《数据表格需求描述》：
 *   默认用户名升序、每页 10 条、字段排序、字段筛选、
 *   多重筛选联动、筛选状态展示、分页数量切换。
 * 数据量通常为测试用户（数百以内），采用前端全量加载 +
 * 客户端筛选/排序/分页，避免后端列表接口改动。
 */
(function (global) {
  'use strict';

  var PROTOCOLS = ['pap', 'chap', 'mschap', 'mschapv2', 'eap-md5'];

  var Page = {
    title: '用户管理',
    desc: '测试用户的增删改查与 CSV 导入导出',
    render: function (container) {
      // ---------- 顶部操作：新增 / 导入 / 导出 ----------
      var toolbar = global.RtUI.card('用户操作');
      var actions = document.createElement('div');
      actions.className = 'app-form-row';

      var addForm = document.createElement('div');
      addForm.className = 'app-form-row';
      addForm.style.flex = '1 1 100%';

      function makeInput(name, placeholder, type, autocomplete) {
        var element = document.createElement('input');
        element.className = 'app-field-input';
        element.name = name;
        element.placeholder = placeholder;
        element.type = type || 'text';
        if (autocomplete) {
          element.setAttribute('autocomplete', autocomplete);
        }
        return element;
      }

      var nameInput = makeInput('username', '用户名', 'text', 'off');
      var passInput = makeInput('password', '密码', 'text', 'new-password');
      var remarkInput = makeInput('remark', '备注', 'text', 'off');
      global.RtUI.validate.bindInput(nameInput, {
        rules: [{ type: 'required' }], label: '用户名'
      });
      global.RtUI.validate.bindInput(passInput, {
        rules: [{ type: 'required' }], label: '密码'
      });
      addForm.appendChild(nameInput);
      addForm.appendChild(passInput);
      addForm.appendChild(remarkInput);

      var addButton = global.RtUI.button('新增用户', 'primary', '/static/svg/action-add.svg');
      addButton.addEventListener('click', function (event) {
        var nameErr = global.RtUI.validate.checkInput(nameInput, nameInput._validateSchema);
        var passErr = global.RtUI.validate.checkInput(passInput, passInput._validateSchema);
        nameInput.classList.toggle('is-invalid', !!nameErr);
        passInput.classList.toggle('is-invalid', !!passErr);
        if (nameErr || passErr) {
          global.RtUI.toast(nameErr || passErr, 'warning');
          (nameErr ? nameInput : passInput).focus();
          return;
        }
        var payload = {
          username: nameInput.value.trim(),
          password: passInput.value,
          remark: remarkInput.value.trim(),
          enabled: true
        };
        global.RtUI.withLoading(addButton, function () {
          return global.RtApi.createUser(payload).then(function () {
            global.RtUI.toast('用户已新增', 'success');
            nameInput.value = '';
            passInput.value = '';
            remarkInput.value = '';
            nameInput.classList.remove('is-invalid');
            passInput.classList.remove('is-invalid');
            return load();
          });
        }, event);
      });
      addForm.appendChild(addButton);
      actions.appendChild(addForm);

      var importRow = document.createElement('div');
      importRow.className = 'app-form-row';

      var fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.accept = '.csv';
      fileInput.className = 'app-field-input app-user-file-input';
      importRow.appendChild(fileInput);

      var overwriteRow = document.createElement('div');
      overwriteRow.className = 'app-checkbox-row';
      var overwriteCheck = document.createElement('input');
      overwriteCheck.type = 'checkbox';
      overwriteCheck.className = 'app-user-overwrite-checkbox';
      var overwriteLabel = document.createElement('span');
      overwriteLabel.className = 'app-checkbox-label';
      overwriteLabel.textContent = '覆盖已有用户';
      overwriteRow.appendChild(overwriteCheck);
      overwriteRow.appendChild(overwriteLabel);
      importRow.appendChild(overwriteRow);

      var importButton = global.RtUI.button('导入 CSV', '', '/static/svg/action-import.svg');
      importButton.addEventListener('click', function (event) {
        if (!fileInput.files || fileInput.files.length === 0) {
          global.RtUI.toast('请先选择 CSV 文件', 'warning');
          return;
        }
        global.RtUI.withLoading(importButton, function () {
          return global.RtApi.importUsers(fileInput.files[0], overwriteCheck.checked)
            .then(function (result) {
              global.RtUI.toast('导入完成：新增 ' + result.added +
                '，更新 ' + result.updated + '，跳过 ' + result.skipped, 'success');
              fileInput.value = '';
              return load();
            });
        }, event);
      });
      importRow.appendChild(importButton);

      var exportButton = global.RtUI.button('导出 CSV', '', '/static/svg/action-export.svg');
      exportButton.addEventListener('click', function (event) {
        global.RtDebug.click(exportButton, event, { result: 'ok', message: 'export' });
        window.location.href = '/api/users/export';
      });
      importRow.appendChild(exportButton);

      actions.appendChild(importRow);
      toolbar.body.appendChild(actions);
      container.appendChild(toolbar.element);

      // ---------- 用户列表 ----------
      var listCard = global.RtUI.card('用户列表');
      var listHost = document.createElement('div');
      listCard.body.appendChild(listHost);
      container.appendChild(listCard.element);

      // 批量操作条
      var batchBar = document.createElement('div');
      batchBar.className = 'app-form-row app-user-batch-bar';

      var selectAll = document.createElement('input');
      selectAll.type = 'checkbox';
      selectAll.className = 'app-user-select-all';
      var selectAllLabel = document.createElement('span');
      selectAllLabel.className = 'app-checkbox-label';
      selectAllLabel.textContent = '全选本页';
      var selectAllWrap = document.createElement('label');
      selectAllWrap.className = 'app-checkbox-row';
      selectAllWrap.appendChild(selectAll);
      selectAllWrap.appendChild(selectAllLabel);
      batchBar.appendChild(selectAllWrap);

      var countText = document.createElement('span');
      countText.className = 'app-user-batch-count';
      countText.textContent = '已选 0 项';
      batchBar.appendChild(countText);

      var serverLabel = document.createElement('span');
      serverLabel.className = 'app-field-hint';
      serverLabel.textContent = '目标 Server';
      var serverSelect = document.createElement('select');
      serverSelect.className = 'app-field-select app-user-batch-server';

      var protoLabel = document.createElement('span');
      protoLabel.className = 'app-field-hint';
      protoLabel.textContent = '协议';
      var protoSelect = document.createElement('select');
      protoSelect.className = 'app-field-select app-user-batch-server';
      PROTOCOLS.forEach(function (p) {
        var option = document.createElement('option');
        option.value = p;
        option.textContent = p;
        protoSelect.appendChild(option);
      });

      batchBar.appendChild(serverLabel);
      batchBar.appendChild(serverSelect);
      batchBar.appendChild(protoLabel);
      batchBar.appendChild(protoSelect);

      var batchTestBtn = global.RtUI.button('批量测试', '', '/static/svg/action-test.svg');
      var batchDeleteBtn = global.RtUI.button('批量删除', 'danger', '/static/svg/action-delete.svg');
      batchBar.appendChild(batchTestBtn);
      batchBar.appendChild(batchDeleteBtn);
      listHost.appendChild(batchBar);

      var tableHost = document.createElement('div');
      listHost.appendChild(tableHost);

      var allUsers = [];
      var selectedUsernames = new Set();
      var table;

      function updateBatchBar() {
        countText.textContent = '已选 ' + selectedUsernames.size + ' 项';
        var hasSel = selectedUsernames.size > 0;
        batchTestBtn.disabled = !hasSel;
        batchDeleteBtn.disabled = !hasSel;
        var pageUsernames = (table && table.rows) ? table.rows.map(function (r) {
          return r.username;
        }) : [];
        selectAll.checked = pageUsernames.length > 0 &&
          pageUsernames.every(function (u) { return selectedUsernames.has(u); });
      }

      function load() {
        return Promise.all([global.RtApi.listUsers(), global.RtApi.listServers()])
          .then(function (res) {
            allUsers = res[0].users || [];
            var servers = res[1].servers || [];
            serverSelect.innerHTML = '';
            servers.forEach(function (s) {
              var option = document.createElement('option');
              option.value = s.name;
              option.textContent = s.name;
              serverSelect.appendChild(option);
            });
            if (servers.length === 0) {
              var empty = document.createElement('option');
              empty.value = '';
              empty.textContent = '暂无 Server';
              serverSelect.appendChild(empty);
            }
            return table.reload();
          });
      }

      // 客户端筛选 / 排序 / 分页
      function applyQuery(query) {
        var params = new URLSearchParams(query);
        var page = parseInt(params.get('page') || '1', 10);
        var pageSize = parseInt(params.get('page_size') || '10', 10);
        var sortField = params.get('sort_field') || 'username';
        var sortOrder = params.get('sort_order') || 'asc';
        var filters = {};
        params.forEach(function (value, key) {
          if (['page', 'page_size', 'sort_field', 'sort_order'].indexOf(key) >= 0) {
            return;
          }
          (filters[key] = filters[key] || []).push(value);
        });
        var rows = allUsers.slice();
        Object.keys(filters).forEach(function (field) {
          var allowed = filters[field];
          rows = rows.filter(function (u) {
            return allowed.indexOf(String(u[field])) >= 0;
          });
        });
        rows.sort(function (a, b) {
          var av = a[sortField];
          var bv = b[sortField];
          if (av === bv) {
            return 0;
          }
          var cmp = av < bv ? -1 : 1;
          return sortOrder === 'asc' ? cmp : -cmp;
        });
        var total = rows.length;
        var start = (page - 1) * pageSize;
        return { rows: rows.slice(start, start + pageSize), total: total };
      }

      function fetchOptions(field, otherFilters) {
        var base = allUsers.slice();
        Object.keys(otherFilters || {}).forEach(function (f) {
          var allowed = otherFilters[f] || [];
          base = base.filter(function (u) {
            return allowed.indexOf(String(u[f])) >= 0;
          });
        });
        var counts = {};
        base.forEach(function (u) {
          var k = String(u[field]);
          counts[k] = (counts[k] || 0) + 1;
        });
        var options = Object.keys(counts).map(function (k) {
          return { value: k, count: counts[k] };
        });
        options.sort(function (a, b) {
          return (b.count - a.count) || (a.value < b.value ? -1 : 1);
        });
        return options;
      }

      function badge(text, kind) {
        var span = document.createElement('span');
        span.className = 'app-badge app-badge-' + (kind || 'muted');
        span.textContent = text;
        return span;
      }

      function showBatchTestResult(results) {
        var host = document.createElement('div');
        var wrap = document.createElement('div');
        wrap.className = 'app-table-wrap';
        var tableEl = document.createElement('table');
        tableEl.className = 'app-table';
        var thead = document.createElement('thead');
        var headRow = document.createElement('tr');
        ['用户名', '连接结果', 'RADIUS 响应结果', '响应时间', '错误原因'].forEach(function (text) {
          var th = document.createElement('th');
          th.textContent = text;
          headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        var tbody = document.createElement('tbody');
        results.forEach(function (r) {
          var tr = document.createElement('tr');
          [r.username, r.connect_result, r.radius_result, r.response_time_ms + ' ms', r.error || '无']
            .forEach(function (value) {
              var td = document.createElement('td');
              td.textContent = String(value === undefined || value === null ? '-' : value);
              tr.appendChild(td);
            });
          tbody.appendChild(tr);
        });
        tableEl.appendChild(thead);
        tableEl.appendChild(tbody);
        wrap.appendChild(tableEl);
        host.appendChild(wrap);
        global.RtUI.modal('批量测试结果 - ' + results.length + ' 个用户', [], [], host);
      }

      table = global.RtTable.create({
        container: tableHost,
        defaultSortField: 'username',
        columns: [
          {
            key: '__select',
            label: '',
            filterable: false,
            sortable: false,
            render: function (row) {
              var cb = document.createElement('input');
              cb.type = 'checkbox';
              cb.className = 'app-user-select-cb';
              cb.checked = selectedUsernames.has(row.username);
              cb.addEventListener('change', function () {
                if (cb.checked) {
                  selectedUsernames.add(row.username);
                } else {
                  selectedUsernames.delete(row.username);
                }
                // 勾选时同步行高亮，避免等重渲染
                var tr = cb.closest ? cb.closest('tr') : null;
                if (tr) {
                  tr.classList.toggle('is-selected', cb.checked);
                }
                updateBatchBar();
              });
              return cb;
            }
          },
          { key: 'username', label: '用户名' },
          {
            key: 'password',
            label: '密码',
            filterable: false,
            render: function (row) { return row.password || ''; }
          },
          {
            key: 'remark',
            label: '备注',
            render: function (row) { return row.remark || ''; }
          },
          {
            key: '__ops',
            label: '操作',
            filterable: false,
            sortable: false,
            render: function (row) {
              var wrapOps = document.createElement('div');
              wrapOps.className = 'app-form-row';
              var test = document.createElement('button');
              test.className = 'app-button app-button-sm';
              test.type = 'button';
              test.textContent = '测试';
              test.style.marginRight = '8px';
              test.addEventListener('click', function () {
                global.RtUI.toast('已跳转至 RADIUS Server 页面，请选择服务器并点击「Radius 用户测试」', 'info');
                window.location.hash = '#/server';
              });
              var del = document.createElement('button');
              del.className = 'app-button app-button-danger app-button-sm';
              del.type = 'button';
              del.textContent = '删除';
              del.addEventListener('click', function () {
                global.RtUI.confirm('删除用户', '确认删除用户「' + row.username + '」？')
                  .then(function (confirmed) {
                    if (!confirmed) {
                      return null;
                    }
                    return global.RtApi.deleteUser(row.username).then(function () {
                      global.RtUI.toast('用户已删除', 'success');
                      selectedUsernames.delete(row.username);
                      return load();
                    });
                  });
              });
              wrapOps.appendChild(test);
              wrapOps.appendChild(del);
              return wrapOps;
            }
          }
        ],
        fetchData: function (query) {
          return Promise.resolve(applyQuery(query));
        },
        fetchOptions: function (field, otherFilters) {
          return Promise.resolve(fetchOptions(field, otherFilters));
        },
        rowClassName: function (row) {
          return selectedUsernames.has(row.username) ? 'is-selected' : '';
        },
        onRowClick: function (row, index, event) {
          // 点击行内的复选框/按钮/链接时不触发行选择
          if (event && event.target && event.target.closest
            && event.target.closest('input, button, a, label')) {
            return;
          }
          // 单选：点击行只选中该行；多选请使用行首复选框
          selectedUsernames.clear();
          selectedUsernames.add(row.username);
          updateBatchBar();
          table.reload();
        }
      });

      selectAll.addEventListener('change', function () {
        var pageUsernames = (table.rows || []).map(function (r) { return r.username; });
        if (selectAll.checked) {
          pageUsernames.forEach(function (u) { selectedUsernames.add(u); });
        } else {
          pageUsernames.forEach(function (u) { selectedUsernames.delete(u); });
        }
        updateBatchBar();
        table.reload();
      });

      batchTestBtn.addEventListener('click', function (event) {
        var server = serverSelect.value;
        if (!server) {
          global.RtUI.toast('请先选择目标 RADIUS Server', 'warning');
          return;
        }
        if (selectedUsernames.size === 0) {
          global.RtUI.toast('请先勾选用户', 'warning');
          return;
        }
        var usernames = Array.from(selectedUsernames);
        global.RtUI.withLoading(batchTestBtn, function () {
          return global.RtApi.batchAuthTest(server, usernames, protoSelect.value)
            .then(function (data) {
              showBatchTestResult(data.results || []);
            });
        }, event);
      });

      batchDeleteBtn.addEventListener('click', function (event) {
        if (selectedUsernames.size === 0) {
          global.RtUI.toast('请先勾选用户', 'warning');
          return;
        }
        var usernames = Array.from(selectedUsernames);
        global.RtUI.confirm('批量删除用户', '确认删除选中的 ' + usernames.length + ' 个用户？')
          .then(function (confirmed) {
            if (!confirmed) {
              return null;
            }
            return global.RtUI.withLoading(batchDeleteBtn, function () {
              return global.RtApi.batchDeleteUsers(usernames).then(function (data) {
                var removed = (data.removed || []).length;
                var failed = (data.failed || []).length;
                global.RtUI.toast('已删除 ' + removed + ' 个用户' +
                  (failed ? '，' + failed + ' 个失败' : ''), 'success');
                selectedUsernames.clear();
                return load();
              });
            }, event);
          });
      });

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.user = Page;
})(window);
