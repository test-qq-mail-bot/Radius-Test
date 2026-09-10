/* RADIUS Dictionary 页面：模板管理。
 *
 * 规则（项目书 18.x）：
 *   1. 内置模板位于源码内部，只读；
 *   2. 自定义模板位于 data/dictionaries/，可增删改；
 *   3. 支持基于内置模板派生自定义模板，用户再自行修改；
 *   4. 非法自定义模板在加载时被忽略。
 */
(function (global) {
  'use strict';

  var Page = {
    title: 'RADIUS Dictionary',
    desc: '内置与自定义 Radius 属性模板管理',
    render: function (container) {
      var deriveCard = global.RtUI.card('派生自定义模板');
      deriveCard.element.id = global.uid('app-dict-derive-card');
      var form = document.createElement('div');
      form.className = 'app-form';
      form.id = global.uid('app-dict-derive-form');
      var row = document.createElement('div');
      row.className = 'app-form-row';
      row.id = global.uid('app-dict-derive-row');

      function makeSelect(className) {
        var element = document.createElement('select');
        element.className = 'app-field-select ' + className;
        return element;
      }

      function makeInput(className, placeholder) {
        var element = document.createElement('input');
        element.className = 'app-field-input ' + className;
        element.type = 'text';
        element.placeholder = placeholder || '';
        return element;
      }

      function box(label, control, hint) {
        var wrapper = document.createElement('div');
        wrapper.className = 'app-field';
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

      var sourceSelect = makeSelect('app-dict-source-select');
      sourceSelect.id = global.uid('app-dict-source');
      var nameInput = makeInput('app-dict-newname-input', '新模板名称');
      nameInput.id = global.uid('app-dict-newname');
      var vendorInput = makeInput('app-dict-vendor-input', '厂商名称');
      vendorInput.id = global.uid('app-dict-vendor');
      var vendorIdInput = makeInput('app-dict-vendorid-input', '厂商编号');
      vendorIdInput.id = global.uid('app-dict-vendorid');

      var sourceBox = box('源模板', sourceSelect, '内置或已有模板');
      var nameBox = box('新模板名称', nameInput, '字母、数字、下划线、短横线');
      var vendorBox = box('厂商名称', vendorInput, '可留空');
      var vendorIdBox = box('厂商编号', vendorIdInput, '可留空，0~65535');

      // 挂校验 schema
      sourceBox._validateSchema = { rules: [{ type: 'required' }], label: '源模板' };
      nameBox._validateSchema = {
        rules: [
          { type: 'required' },
          { type: 'pattern', pattern: '^[A-Za-z0-9_\\-]+$', hint: '只能包含字母、数字、下划线、短横线' }
        ],
        label: '新模板名称'
      };
      vendorBox._validateSchema = { rules: [], label: '厂商名称' };
      vendorIdBox._validateSchema = {
        rules: [{ type: 'integer', optional: true, min: 0, max: 65535 }],
        label: '厂商编号'
      };
      global.RtUI.validate.bindField(sourceBox, sourceBox._validateSchema);
      global.RtUI.validate.bindField(nameBox, nameBox._validateSchema);
      global.RtUI.validate.bindField(vendorIdBox, vendorIdBox._validateSchema);

      row.appendChild(sourceBox);
      row.appendChild(nameBox);
      row.appendChild(vendorBox);
      row.appendChild(vendorIdBox);
      form.appendChild(row);

      var buttonRow = document.createElement('div');
      buttonRow.className = 'app-form-row';
      buttonRow.id = global.uid('app-dict-derive-button-row');
      var deriveButton = global.RtUI.button('派生为自定义模板', 'primary');
      deriveButton.id = global.uid('app-dict-derive');
      buttonRow.appendChild(deriveButton);
      form.appendChild(buttonRow);
      deriveCard.body.appendChild(form);
      container.appendChild(deriveCard.element);

      var uploadCard = global.RtUI.card('上传自定义模板');
      uploadCard.element.id = global.uid('app-dict-upload-card');
      var uploadRow = document.createElement('div');
      uploadRow.className = 'app-form-row';
      uploadRow.id = global.uid('app-dict-upload-row');
      var fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.id = global.uid('app-dict-upload-file');
      fileInput.accept = '.yaml,.yml';
      fileInput.className = 'app-field-input app-dict-file-input';
      uploadRow.appendChild(fileInput);
      var uploadButton = global.RtUI.button('上传 YAML', '');
      uploadButton.id = global.uid('app-dict-upload');
      uploadRow.appendChild(uploadButton);
      uploadCard.body.appendChild(uploadRow);
      container.appendChild(uploadCard.element);

      var listCard = global.RtUI.card('模板列表');
      listCard.element.id = global.uid('app-dict-list-card');
      var listHost = document.createElement('div');
      listHost.id = global.uid('app-dict-list-host');
      listCard.body.appendChild(listHost);
      container.appendChild(listCard.element);

      deriveButton.addEventListener('click', function (event) {
        // 提交前校验
        var result = global.RtUI.validate.validateForm(
          [sourceBox, nameBox, vendorIdBox]
        );
        if (!result.valid) {
          global.RtUI.toast('请检查表单中标红的字段', 'warning');
          if (result.firstInvalid && result.firstInvalid.scrollIntoView) {
            result.firstInvalid.scrollIntoView({ block: 'center' });
          }
          return;
        }
        var payload = {
          source: sourceSelect.value,
          new_name: nameInput.value.trim(),
          vendor: vendorInput.value.trim()
        };
        if (vendorIdInput.value.trim()) {
          payload.vendor_id = parseInt(vendorIdInput.value.trim(), 10);
        }
        global.RtUI.withLoading(deriveButton, function () {
          return global.RtApi.deriveTemplate(payload).then(function (result) {
            global.RtUI.toast('已派生模板：' + result.file +
              '（' + result.attribute_count + ' 条属性）', 'success');
            nameInput.value = '';
            // 清掉所有错误
            [sourceBox, nameBox, vendorIdBox].forEach(function (b) {
              global.RtUI.validate.clearError(b);
            });
            return load();
          });
        }, event);
      });

      uploadButton.addEventListener('click', function (event) {
        if (!fileInput.files || fileInput.files.length === 0) {
          global.RtUI.toast('请先选择 YAML 文件', 'warning');
          return;
        }
        global.RtUI.withLoading(uploadButton, function () {
          return global.RtApi.uploadTemplate(fileInput.files[0]).then(function () {
            global.RtUI.toast('模板已上传', 'success');
            fileInput.value = '';
            return load();
          });
        }, event);
      });

      function load() {
        return global.RtApi.listTemplates().then(function (data) {
          var templates = data.templates || [];
          sourceSelect.innerHTML = '';
          templates.forEach(function (template) {
            var option = document.createElement('option');
            option.value = template.template;
            option.textContent = template.template +
              '（' + template.source + '，' + template.attribute_count + ' 条）';
            sourceSelect.appendChild(option);
          });

          listHost.innerHTML = '';
          templates.forEach(function (template) {
            var card = global.RtUI.card(template.template);
            card.element.id = global.uid('app-dict-item-' + template.template);
            var info = document.createElement('div');
            info.className = 'app-detail-list';
            [
              ['来源', template.source === 'builtin' ? '内置（只读）' : '自定义'],
              ['厂商', template.vendor || '-'],
              ['厂商编号', template.vendor_id === null || template.vendor_id === undefined
                ? '-' : template.vendor_id],
              ['属性数量', template.attribute_count],
              ['文件', template.file || '-']
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

            var viewButton = document.createElement('button');
            viewButton.className = 'app-button app-dict-view-button';
            viewButton.type = 'button';
            viewButton.id = global.uid('app-dict-view-' + template.template);
            viewButton.textContent = '查看属性';
            viewButton.addEventListener('click', function () {
              global.RtApi.getTemplate(template.template).then(function (detail) {
                showAttributes(detail);
              });
            });
            actions.appendChild(viewButton);

            var exportButton = document.createElement('button');
            exportButton.className = 'app-button app-dict-export-button';
            exportButton.type = 'button';
            exportButton.id = global.uid('app-dict-export-' + template.template);
            exportButton.textContent = '导出 YAML';
            exportButton.addEventListener('click', function () {
              window.location.href = '/api/dictionaries/' +
                encodeURIComponent(template.template) + '/export';
            });
            actions.appendChild(exportButton);

            if (template.source === 'custom') {
              var deleteButton = document.createElement('button');
              deleteButton.className = 'app-button app-button-danger app-dict-delete-button';
              deleteButton.type = 'button';
              deleteButton.id = global.uid('app-dict-delete-' + template.template);
              deleteButton.textContent = '删除';
              deleteButton.addEventListener('click', function () {
                global.RtUI.confirm('删除模板', '确认删除自定义模板「' + template.template + '」？')
                  .then(function (confirmed) {
                    if (!confirmed) {
                      return null;
                    }
                    return global.RtApi.deleteTemplate(template.template).then(function () {
                      global.RtUI.toast('模板已删除', 'success');
                      return load();
                    });
                  });
              });
              actions.appendChild(deleteButton);
            }

            card.body.appendChild(actions);
            listHost.appendChild(card.element);
          });
        });
      }

      function showAttributes(detail) {
        var host = document.createElement('div');
        host.className = 'app-dict-attr-host';
        host.id = global.uid('app-dict-attr-host');
        var attributes = (detail.attributes || []).map(function (item) {
          return {
            id: item.id,
            name: item.name || '',
            name_zh: item.name_zh || '',
            type: item.type || '',
            desc: item.desc || ''
          };
        });

        /* 客户端排序 / 筛选 / 分页：与《数据表格需求描述》一致 */
        function applyQuery(query) {
          var params = new URLSearchParams(query);
          var page = parseInt(params.get('page') || '1', 10);
          var pageSize = parseInt(params.get('page_size') || '10', 10);
          var sortField = params.get('sort_field') || 'id';
          var sortOrder = params.get('sort_order') || 'asc';
          var filters = {};
          params.forEach(function (value, key) {
            if (['page', 'page_size', 'sort_field', 'sort_order'].indexOf(key) >= 0) {
              return;
            }
            (filters[key] = filters[key] || []).push(value);
          });
          var rows = attributes.slice();
          Object.keys(filters).forEach(function (field) {
            var allowed = filters[field];
            rows = rows.filter(function (row) {
              return allowed.indexOf(String(row[field])) >= 0;
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
          var start = (page - 1) * pageSize;
          return { rows: rows.slice(start, start + pageSize), total: rows.length };
        }

        /* 筛选联动：可选项基于「除本字段以外」的筛选条件计算 */
        function fetchOptions(field, otherFilters) {
          var rows = attributes.slice();
          Object.keys(otherFilters || {}).forEach(function (key) {
            rows = rows.filter(function (row) {
              return (otherFilters[key] || []).indexOf(String(row[key])) >= 0;
            });
          });
          var counter = {};
          rows.forEach(function (row) {
            var value = String(row[field] === undefined || row[field] === null
              ? '' : row[field]);
            counter[value] = (counter[value] || 0) + 1;
          });
          return Promise.resolve(Object.keys(counter).sort().map(function (value) {
            return { value: value, count: counter[value] };
          }));
        }

        var attrTable = global.RtTable.create({
          container: host,
          defaultSortField: 'id',
          columns: [
            { key: 'id', label: '编号', filterable: false },
            { key: 'name', label: '属性名' },
            { key: 'name_zh', label: '中文名' },
            { key: 'type', label: '类型' },
            { key: 'desc', label: '说明', filterable: false }
          ],
          fetchData: function (query) {
            return Promise.resolve(applyQuery(query));
          },
          fetchOptions: function (field, others) {
            return fetchOptions(field, others);
          }
        });

        global.RtUI.modal('模板属性 - ' + detail.template, [], [], host);
        // 属性表列多，弹窗需要加宽以在常用分辨率下显示完整
        var panel = document.getElementById('modal-panel');
        if (panel) {
          panel.classList.add('is-wide');
        }
        // 弹窗挂载后再加载首屏数据
        attrTable.reload();
      }

      global.RtUI.bindRefresh(load);
      return load();
    }
  };

  global.RtPages = global.RtPages || {};
  global.RtPages.dict = Page;
})(window);
