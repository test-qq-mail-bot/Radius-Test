/* 用户管理页面：用户管理、CSV 导入、选中导出、批量测试/删除。
 *
 * 表格严格遵循《数据表格需求描述》：
 *   默认用户名升序、每页 10 条、字段排序、字段筛选、
 *   多重筛选联动、筛选状态展示、分页数量切换。
 * 数据量通常为测试用户（数百以内），采用前端全量加载 +
 * 客户端筛选/排序/分页，避免后端列表接口改动。
 *
 * 用户数据规则：
 *   1. 用户名是唯一键，保存时同名即覆盖；
 *   2. 密码留空代表「不修改密码」（已存在用户保留原密码），新用户必须填密码；
 *   3. 列表不展示密码列；
 *   4. 导入为逐行容错：合法行全部导入，非法行返回明细；导入一律覆盖同名用户。
 */
(function (global) {
  'use strict';

  var PROTOCOLS = ['pap', 'chap', 'mschap', 'mschapv2', 'eap-md5'];

  function safeId(s) {
    return String(s == null ? '' : s).replace(/[^A-Za-z0-9_-]/g, '_') || 'x';
  }

  /* CSV 单元格转义：含逗号/引号/换行时用双引号包裹，内部引号翻倍 */
  function csvCell(value) {
    var text = String(value === undefined || value === null ? '' : value);
    if (text.indexOf(',') >= 0 || text.indexOf('"') >= 0 ||
        text.indexOf('\n') >= 0 || text.indexOf('\r') >= 0) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  /* 把二维数据下载为 CSV 文件（带 BOM，保证 Excel 正确识别 UTF-8） */
  function downloadCsv(filename, rows) {
    var lines = rows.map(function (cells) {
      return cells.map(csvCell).join(',');
    });
    var blob = new Blob(['\ufeff' + lines.join('\r\n')], {
      type: 'text/csv;charset=utf-8'
    });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  var Page = {
    title: '用户管理',
    desc: '测试用户的增删改查与 CSV 导入导出',
    render: function (container) {
      // ---------- 顶部操作：表单 + 保存 / 导入用户 ----------
      var toolbar = global.RtUI.card('用户操作');
      toolbar.element.id = global.uid('app-user-toolbar-card');
      var actions = document.createElement('div');
      actions.className = 'app-form-row';
      actions.id = global.uid('app-user-toolbar-actions');

      var addForm = document.createElement('div');
      addForm.className = 'app-form-row';
      addForm.style.flex = '1 1 100%';
      addForm.id = global.uid('app-user-add-form');

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
      nameInput.id = global.uid('app-user-name-input');
      /* 密码框使用密文组件（password + 眼睛切换）；passInput 仍指向内部 input，
         保持取值、校验与聚焦逻辑不变。 */
      var passWrap = global.RtUI.secretInput('password', '', null);
      passWrap.id = global.uid('app-user-password-wrap');
      var passInput = passWrap.querySelector('.app-secret-input-field');
      passInput.id = global.uid('app-user-password-input');
      passInput.placeholder = '密码';
      var remarkInput = makeInput('remark', '备注', 'text', 'off');
      remarkInput.id = global.uid('app-user-remark-input');
      global.RtUI.validate.bindInput(nameInput, {
        rules: [{ type: 'required' }], label: '用户名'
      });
      // 密码不再强制必填：留空代表「不修改密码」，仅新用户要求必填（见保存逻辑）
      addForm.appendChild(nameInput);
      addForm.appendChild(passWrap);
      addForm.appendChild(remarkInput);

      var allUsers = [];
      var selectedUsernames = new Set();
      var table;

      function findUser(username) {
        for (var i = 0; i < allUsers.length; i += 1) {
          if (allUsers[i].username === username) {
            return allUsers[i];
          }
        }
        return null;
      }

      /* 保存：用户名唯一键，同名覆盖；密码留空则不修改原密码 */
      var saveButton = global.RtUI.button('保存', 'primary');
      saveButton.id = global.uid('app-user-save');
      saveButton.addEventListener('click', function (event) {
        var nameErr = global.RtUI.validate.checkInput(nameInput, nameInput._validateSchema);
        nameInput.classList.toggle('is-invalid', !!nameErr);
        if (nameErr) {
          global.RtUI.toast(nameErr, 'warning');
          nameInput.focus();
          return;
        }
        var username = nameInput.value.trim();
        var password = passInput.value;
        // 仅新用户必须提供密码；已存在用户留空表示不修改密码
        if (!findUser(username) && !password) {
          passInput.classList.add('is-invalid');
          global.RtUI.toast('新用户必须填写密码（已存在用户留空表示不修改）', 'warning');
          passInput.focus();
          return;
        }
        passInput.classList.remove('is-invalid');
        var payload = {
          username: username,
          password: password,
          remark: remarkInput.value.trim()
        };
        global.RtUI.withLoading(saveButton, function () {
          return global.RtApi.createUser(payload).then(function (result) {
            var updated = !!(result && result.updated);
            global.RtUI.toast(updated ? '已更新用户：' + username : '已新增用户：' + username,
              'success');
            nameInput.value = '';
            passInput.value = '';
            remarkInput.value = '';
            nameInput.classList.remove('is-invalid');
            passInput.classList.remove('is-invalid');
            return load();
          });
        }, event);
      });
      addForm.appendChild(saveButton);

      /* 导入用户：弹窗内完成 下载模板 / 选择文件 / 预览文本 / 提交导入 */
      var importUserButton = global.RtUI.button('导入用户', '');
      importUserButton.id = global.uid('app-user-import-open');
      importUserButton.addEventListener('click', function () {
        openImportModal();
      });
      addForm.appendChild(importUserButton);

      actions.appendChild(addForm);
      toolbar.body.appendChild(actions);
      container.appendChild(toolbar.element);

      // ---------- 用户列表 ----------
      var listCard = global.RtUI.card('用户列表');
      listCard.element.id = global.uid('app-user-list-card');
      var listHost = document.createElement('div');
      listHost.id = global.uid('app-user-list-host');
      listCard.body.appendChild(listHost);
      container.appendChild(listCard.element);

      // 批量操作条
      var batchBar = document.createElement('div');
      batchBar.className = 'app-form-row app-user-batch-bar';
      batchBar.id = 'app-user-batch-bar';

      var selectAll = document.createElement('input');
      selectAll.type = 'checkbox';
      selectAll.className = 'app-user-select-all';
      selectAll.id = 'app-user-select-all';
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
      countText.id = 'app-user-batch-count';
      countText.textContent = '已选 0 项';
      batchBar.appendChild(countText);

      var serverLabel = document.createElement('span');
      serverLabel.className = 'app-field-hint';
      serverLabel.textContent = '目标 Server';
      var serverSelect = document.createElement('select');
      serverSelect.className = 'app-field-select app-user-batch-server';
      serverSelect.id = 'app-user-batch-server';

      var protoLabel = document.createElement('span');
      protoLabel.className = 'app-field-hint';
      protoLabel.textContent = '协议';
      var protoSelect = document.createElement('select');
      protoSelect.className = 'app-field-select app-user-batch-server';
      protoSelect.id = 'app-user-batch-protocol';
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

      var batchTestBtn = global.RtUI.button('批量测试', '');
      batchTestBtn.id = 'app-user-batch-test';
      var batchDeleteBtn = global.RtUI.button('批量删除', 'danger');
      batchDeleteBtn.id = 'app-user-batch-delete';
      var exportCsvBtn = global.RtUI.button('导出 CSV', '');
      exportCsvBtn.id = 'app-user-batch-export';
      batchBar.appendChild(batchTestBtn);
      batchBar.appendChild(batchDeleteBtn);
      batchBar.appendChild(exportCsvBtn);
      listHost.appendChild(batchBar);

      var tableHost = document.createElement('div');
      tableHost.id = global.uid('app-user-table-host');
      listHost.appendChild(tableHost);

      function updateBatchBar() {
        countText.textContent = '已选 ' + selectedUsernames.size + ' 项';
        var hasSel = selectedUsernames.size > 0;
        batchTestBtn.disabled = !hasSel;
        batchDeleteBtn.disabled = !hasSel;
        exportCsvBtn.disabled = !hasSel;
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

      function showBatchTestResult(results) {
        var host = document.createElement('div');
        host.id = global.uid('app-user-batch-result-host');
        var wrap = document.createElement('div');
        wrap.className = 'app-table-wrap';
        var tableEl = document.createElement('table');
        tableEl.className = 'app-table';
        tableEl.id = global.uid('app-user-batch-result-table');
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

      /* 导入失败明细表 */
      function showImportFailures(failures) {
        var host = document.createElement('div');
        host.id = global.uid('app-user-import-failures-host');
        var wrap = document.createElement('div');
        wrap.className = 'app-table-wrap';
        var tableEl = document.createElement('table');
        tableEl.className = 'app-table';
        tableEl.id = global.uid('app-user-import-failures-table');
        var thead = document.createElement('thead');
        var headRow = document.createElement('tr');
        ['行号', '用户名', '失败原因'].forEach(function (text) {
          var th = document.createElement('th');
          th.textContent = text;
          headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        var tbody = document.createElement('tbody');
        failures.forEach(function (item) {
          var tr = document.createElement('tr');
          [item.line || '-', item.username || '-', item.reason || '-'].forEach(function (value) {
            var td = document.createElement('td');
            td.textContent = String(value);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        tableEl.appendChild(thead);
        tableEl.appendChild(tbody);
        wrap.appendChild(tableEl);
        host.appendChild(wrap);
        global.RtUI.modal('导入失败明细 - ' + failures.length + ' 条', [], [], host);
      }

      /* 导入用户弹窗：规范提示 + 文本框 + 下载模板 + 选择文件 + 导入用户 */
      function openImportModal() {
        var host = document.createElement('div');
        host.className = 'app-form';
        host.id = global.uid('app-user-import-host');

        var tip = document.createElement('div');
        tip.className = 'app-field-hint app-user-import-tip';
        tip.id = global.uid('app-user-import-tip');
        tip.textContent = '导入文件为 CSV 格式，首行为表头：username,password,remark。'
          + 'username 必填，是唯一键，同名即覆盖；'
          + 'password 新用户必填，已存在用户留空表示不修改原密码；'
          + 'remark 可为空。'
          + '以 # 开头的行与空行会被忽略，文件需为 UTF-8 编码。'
          + '合法行全部导入，非法行会跳过并在导入结果中逐行列出原因。';
        host.appendChild(tip);

        var area = document.createElement('textarea');
        area.className = 'app-field-textarea app-user-import-textarea';
        area.id = global.uid('app-user-import-textarea');
        area.rows = 10;
        area.placeholder = '可粘贴 CSV 内容，或点击「选择文件」读取 .csv 文件';
        host.appendChild(area);

        var fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.id = global.uid('app-user-import-file');
        fileInput.accept = '.csv';
        fileInput.hidden = true;
        host.appendChild(fileInput);

        var pickRow = document.createElement('div');
        pickRow.className = 'app-form-row';
        var downloadBtn = global.RtUI.button('导入文件下载', '');
        downloadBtn.id = global.uid('app-user-import-download');
        var pickBtn = global.RtUI.button('选择文件', '');
        pickBtn.id = global.uid('app-user-import-pick');
        pickRow.appendChild(downloadBtn);
        pickRow.appendChild(pickBtn);
        host.appendChild(pickRow);

        var importBtn = global.RtUI.button('导入用户', 'primary');
        importBtn.id = global.uid('app-user-import-submit');
        var closeBtn = global.RtUI.button('关闭', '');
        closeBtn.id = global.uid('app-user-import-close');
        closeBtn.addEventListener('click', function () {
          global.RtUI.closeModal();
        });

        downloadBtn.addEventListener('click', function () {
          window.location.href = '/api/users/template';
        });

        pickBtn.addEventListener('click', function () {
          fileInput.click();
        });

        fileInput.addEventListener('change', function () {
          var file = fileInput.files && fileInput.files[0];
          if (!file) {
            return;
          }
          var name = (file.name || '').toLowerCase();
          // 只允许 CSV：在 accept 之外再校验一次，避免用户手动绕过文件类型过滤
          if (name.slice(-4) !== '.csv') {
            global.RtUI.toast('只能选择 CSV 文件', 'warning');
            fileInput.value = '';
            return;
          }
          var reader = new FileReader();
          reader.onload = function () {
            area.value = String(reader.result || '');
            global.RtUI.toast('已读取文件：' + file.name, 'success');
          };
          reader.onerror = function () {
            global.RtUI.toast('文件读取失败', 'error');
          };
          reader.readAsText(file, 'utf-8');
        });

        importBtn.addEventListener('click', function (event) {
          if (!area.value.trim()) {
            global.RtUI.toast('请先选择 CSV 文件或粘贴 CSV 内容', 'warning');
            return;
          }
          global.RtUI.withLoading(importBtn, function () {
            return global.RtApi.importUsers(area.value).then(function (result) {
              if (!result || result.success === false) {
                global.RtUI.toast((result && result.message) || '导入失败', 'error');
                return null;
              }
              var added = result.added || 0;
              var updated = result.updated || 0;
              var failed = result.failed || 0;
              global.RtUI.toast('导入完成：成功 ' + (added + updated) +
                '（新增 ' + added + '，覆盖 ' + updated + '），失败 ' + failed,
                failed > 0 ? 'warning' : 'success');
              var failures = result.failures || [];
              global.RtUI.closeModal();
              return load().then(function () {
                if (failed > 0 && failures.length) {
                  showImportFailures(failures);
                }
                return null;
              });
            });
          }, event);
        });

        global.RtUI.modal('导入用户', [], [importBtn, closeBtn], host);
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
              test.id = 'app-user-test-' + safeId(row.username);
              test.addEventListener('click', function (event) {
                var server = serverSelect.value;
                if (!server) {
                  global.RtUI.toast('请先在上方选择目标 RADIUS Server', 'warning');
                  return;
                }
                global.RtUI.withLoading(test, function () {
                  return global.RtApi.batchAuthTest(server, [row.username], protoSelect.value)
                    .then(function (data) {
                      showBatchTestResult(data.results || []);
                    });
                }, event);
              });

              var edit = document.createElement('button');
              edit.className = 'app-button app-button-sm';
              edit.type = 'button';
              edit.textContent = '修改';
              edit.style.marginRight = '8px';
              edit.addEventListener('click', function () {
                // 只回填用户名与备注；密码不回填，留空表示不修改
                nameInput.value = row.username || '';
                remarkInput.value = row.remark || '';
                passInput.value = '';
                nameInput.classList.remove('is-invalid');
                passInput.classList.remove('is-invalid');
                global.RtUI.toast('已载入「' + row.username + '」，修改后点击保存（密码留空则不修改）', 'info');
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
              wrapOps.appendChild(edit);
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
        // 首次渲染与翻页/排序/筛选后都同步批量条：无选中时批量按钮必须禁用
        onRendered: function () {
          updateBatchBar();
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

      // 初始无选中：批量测试 / 批量删除 / 导出 CSV 均置灰
      updateBatchBar();

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

      /* 导出选中用户：密码字段置空，用于不含密数据的报表/迁移 */
      exportCsvBtn.addEventListener('click', function (event) {
        if (selectedUsernames.size === 0) {
          global.RtUI.toast('请先勾选要导出的用户', 'warning');
          return;
        }
        // 按用户列表原始顺序导出，避免勾选顺序导致结果不稳定
        var rows = allUsers.filter(function (u) {
          return selectedUsernames.has(u.username);
        });
        var body = rows.map(function (u) {
          return [u.username, '', u.remark || ''];
        });
        downloadCsv('users-selected.csv',
          [['username', 'password', 'remark']].concat(body));
        global.RtUI.toast('已导出 ' + rows.length + ' 个用户（密码已置空）', 'success');
        if (global.RtDebug) {
          global.RtDebug.click(exportCsvBtn, event, {
            result: 'ok', message: 'export-selected:' + rows.length
          });
        }
      });

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.user = Page;
})(window);
