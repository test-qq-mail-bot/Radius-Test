/* 通用数据表格组件。
 *
 * 严格遵循《数据表格需求描述》：
 *   1. 默认按指定字段升序排列，默认每页 10 条；
 *   2. 点击表头除筛选按钮以外的任意区域触发排序，排序状态循环切换；
 *   3. 筛选面板提供 升序 / 降序 / 全选 / 反选 / 重复项 / 唯一项；
 *   4. 多字段筛选之间为 AND 关系；
 *   5. 筛选项联动：每次筛选后其他字段的可选项基于当前结果集重新计算；
 *   6. 分页区域：数据总量 -> 每页数量 -> 上一页 -> 数字页码 -> 下一页；
 *   7. 数字页码采用「当前页 ± 2」滑动窗口，最多显示 5 个页码；
 *   8. 空数据时展示「暂无符合条件的数据」。
 */
(function (global) {
  'use strict';

  var PAGE_SIZES = [10, 20, 50, 100];
  var MAX_PAGE_BUTTONS = 5;
  /* 表格实例序号：保证同一页面存在多个表格时 id 仍唯一 */
  var TABLE_SEQ = 0;

  function createElement(tag, className, text) {
    var element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }
    return element;
  }

  function Table(config) {
    this.container = config.container;
    this.id = config.tableId || ('app-table-' + (++TABLE_SEQ));
    this.columns = config.columns || [];
    this.fetchData = config.fetchData;
    this.fetchOptions = config.fetchOptions;
    this.onRowClick = config.onRowClick;
    /* rowClassName(row, index)：返回附加到行 tr 的自定义类名（如选中高亮） */
    this.rowClassName = config.rowClassName;
    /* onRendered()：每次表体渲染完成后回调，供外部同步「全选本页」等联动状态 */
    this.onRendered = config.onRendered;
    this.defaultSortField = config.defaultSortField || this.columns[0].key;
    this.defaultSortOrder = config.defaultSortOrder || 'asc';
    this.pageSize = 10;
    this.page = 1;
    this.total = 0;
    this.sortField = this.defaultSortField;
    this.sortOrder = this.defaultSortOrder;
    /* filters: { field: [已选中的取值] } */
    this.filters = {};
    /* options: { field: [{value, count}] } */
    this.options = {};
    this.rows = [];
    this.loading = false;
    this._build();
  }

  Table.prototype._build = function () {
    this.wrap = createElement('div', 'app-table-wrap');
    this.wrap.id = this.id + '-wrap';
    this.table = createElement('table', 'app-table');
    this.table.id = this.id;
    this.thead = createElement('thead', 'app-table-head');
    this.thead.id = this.id + '-head';
    this.tbody = createElement('tbody', 'app-table-body');
    this.tbody.id = this.id + '-body';
    this.table.appendChild(this.thead);
    this.table.appendChild(this.tbody);
    this.wrap.appendChild(this.table);

    this.empty = createElement('div', 'app-table-empty', '暂无符合条件的数据');
    this.empty.id = this.id + '-empty';
    this.empty.hidden = true;

    this.pagination = createElement('div', 'app-pagination');
    this.pagination.id = this.id + '-pagination';

    this.container.appendChild(this.wrap);
    this.container.appendChild(this.empty);
    this.container.appendChild(this.pagination);

    this._renderHeader();
  };

  Table.prototype._renderHeader = function () {
    var self = this;
    this.thead.innerHTML = '';
    var row = createElement('tr', 'app-table-header-row');
    this.columns.forEach(function (column) {
      var th = createElement('th', 'app-table-header-cell');
      th.dataset.field = column.key;
      th.id = self.id + '-th-' + column.key;
      var inner = createElement('div', 'app-table-th-inner');

      var label = createElement('span', 'app-table-th-label', column.label);
      label.addEventListener('click', function (event) {
        if (column.sortable !== false) {
          self._toggleSort(column.key, event);
        }
      });

      var sortIcon = document.createElement('img');
      sortIcon.className = 'app-table-sort';
      sortIcon.id = self.id + '-sort-' + column.key;
      sortIcon.alt = '';
      sortIcon.hidden = true;

      inner.appendChild(label);
      inner.appendChild(sortIcon);

      if (column.filterable !== false) {
        var filterButton = createElement('button', 'app-table-filter-button');
        filterButton.type = 'button';
        filterButton.id = self.id + '-filter-' + column.key;
        filterButton.title = '筛选';
        var filterIcon = document.createElement('img');
        filterIcon.className = 'app-table-filter-icon';
        filterIcon.src = '/static/svg/table-filter.svg';
        filterIcon.alt = '';
        filterButton.appendChild(filterIcon);
        filterButton.addEventListener('click', function (event) {
          event.stopPropagation();
          self._openFilterPanel(column, filterButton);
        });
        inner.appendChild(filterButton);
        column._filterButton = filterButton;
      }

      th.appendChild(inner);
      row.appendChild(th);
      column._sortIcon = sortIcon;
    });
    this.thead.appendChild(row);
    this._updateSortIcons();
  };

  Table.prototype._updateSortIcons = function () {
    var self = this;
    this.columns.forEach(function (column) {
      if (!column._sortIcon) {
        return;
      }
      if (self.sortField === column.key) {
        column._sortIcon.hidden = false;
        column._sortIcon.src = self.sortOrder === 'asc'
          ? '/static/svg/table-sort-asc.svg'
          : '/static/svg/table-sort-desc.svg';
      } else {
        column._sortIcon.hidden = true;
      }
      if (column._filterButton) {
        var selected = self.filters[column.key] || [];
        if (selected.length > 0) {
          column._filterButton.classList.add('is-active');
        } else {
          column._filterButton.classList.remove('is-active');
        }
      }
    });
  };

  /* 排序：升序 -> 降序 -> 升序，切换排序不清空筛选条件 */
  Table.prototype._toggleSort = function (field, event) {
    if (this.sortField === field) {
      this.sortOrder = this.sortOrder === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortField = field;
      this.sortOrder = 'asc';
    }
    if (global.RtDebug) {
      global.RtDebug.click(event && event.target, 'sort', {
        result: 'ok',
        message: 'field=' + field + ';order=' + this.sortOrder
      });
    }
    this._updateSortIcons();
    this.reload({ keepPage: false });
  };

  Table.prototype._openFilterPanel = function (column, anchor) {
    var self = this;
    var existing = this.container.querySelector('.app-filter-panel');
    if (existing && existing.dataset.field === column.key) {
      existing.remove();
      return;
    }
    if (existing) {
      existing.remove();
    }
    var panel = createElement('div', 'app-filter-panel');
    panel.dataset.field = column.key;
    panel.id = this.id + '-panel-' + column.key;
    var panelPrefix = this.id + '-panel-' + column.key + '-';

    var actions = createElement('div', 'app-filter-actions');
    actions.id = panelPrefix + 'actions';
    var sortAsc = createElement('button', 'app-filter-action', '升序');
    sortAsc.type = 'button';
    sortAsc.id = panelPrefix + 'sort-asc';
    sortAsc.addEventListener('click', function () {
      self.sortField = column.key;
      self.sortOrder = 'asc';
      self._updateSortIcons();
      panel.remove();
      self.reload({ keepPage: false });
    });
    var sortDesc = createElement('button', 'app-filter-action', '降序');
    sortDesc.type = 'button';
    sortDesc.id = panelPrefix + 'sort-desc';
    sortDesc.addEventListener('click', function () {
      self.sortField = column.key;
      self.sortOrder = 'desc';
      self._updateSortIcons();
      panel.remove();
      self.reload({ keepPage: false });
    });
    var selectAll = createElement('button', 'app-filter-action', '全选');
    selectAll.type = 'button';
    selectAll.id = panelPrefix + 'select-all';
    selectAll.addEventListener('click', function () {
      var inputs = panel.querySelectorAll('input[type=checkbox]');
      Array.prototype.forEach.call(inputs, function (input) {
        input.checked = true;
      });
    });
    var invert = createElement('button', 'app-filter-action', '反选');
    invert.type = 'button';
    invert.id = panelPrefix + 'invert';
    invert.addEventListener('click', function () {
      var inputs = panel.querySelectorAll('input[type=checkbox]');
      Array.prototype.forEach.call(inputs, function (input) {
        input.checked = !input.checked;
      });
    });
    var duplicate = createElement('button', 'app-filter-action', '重复项');
    duplicate.type = 'button';
    duplicate.id = panelPrefix + 'duplicate';
    duplicate.addEventListener('click', function () {
      var inputs = panel.querySelectorAll('input[type=checkbox]');
      Array.prototype.forEach.call(inputs, function (input) {
        input.checked = parseInt(input.dataset.count || '0', 10) > 1;
      });
    });
    var unique = createElement('button', 'app-filter-action', '唯一项');
    unique.type = 'button';
    unique.id = panelPrefix + 'unique';
    unique.addEventListener('click', function () {
      var inputs = panel.querySelectorAll('input[type=checkbox]');
      Array.prototype.forEach.call(inputs, function (input) {
        input.checked = parseInt(input.dataset.count || '0', 10) === 1;
      });
    });
    [sortAsc, sortDesc, selectAll, invert, duplicate, unique].forEach(function (button) {
      actions.appendChild(button);
    });
    panel.appendChild(actions);

    var options = this.options[column.key] || [];
    var selected = this.filters[column.key] || [];
    if (options.length === 0) {
      panel.appendChild(createElement('div', 'app-filter-option', '（无可用选项）'));
    }
    options.forEach(function (option) {
      var optionSafe = String(option.value).replace(/[^A-Za-z0-9_-]/g, '_') || 'x';
      var label = createElement('label', 'app-filter-option');
      label.id = panelPrefix + 'option-label-' + optionSafe;
      var input = document.createElement('input');
      input.type = 'checkbox';
      input.value = option.value;
      input.id = panelPrefix + 'option-' + optionSafe;
      input.dataset.count = String(option.count || 0);
      input.checked = selected.indexOf(option.value) >= 0;
      var text = createElement('span', 'app-filter-option-text',
        option.value + ' (' + (option.count || 0) + ')');
      label.appendChild(input);
      label.appendChild(text);
      panel.appendChild(label);
    });

    var footer = createElement('div', 'app-filter-actions');
    footer.id = panelPrefix + 'footer';
    var clear = createElement('button', 'app-filter-action', '清除');
    clear.type = 'button';
    clear.id = panelPrefix + 'clear';
    clear.addEventListener('click', function () {
      Array.prototype.forEach.call(panel.querySelectorAll('input[type=checkbox]'), function (input) {
        input.checked = false;
      });
      self._applyFilter(column.key, []);
      panel.remove();
    });
    var apply = createElement('button', 'app-filter-action', '确定');
    apply.type = 'button';
    apply.id = panelPrefix + 'apply';
    apply.addEventListener('click', function () {
      var values = [];
      Array.prototype.forEach.call(panel.querySelectorAll('input[type=checkbox]'), function (input) {
        if (input.checked) {
          values.push(input.value);
        }
      });
      self._applyFilter(column.key, values);
      panel.remove();
    });
    footer.appendChild(clear);
    footer.appendChild(apply);
    panel.appendChild(footer);

    this.wrap.appendChild(panel);
    var rect = anchor.getBoundingClientRect();
    var hostRect = this.wrap.getBoundingClientRect();
    panel.style.left = Math.max(0, rect.left - hostRect.left - 40) + 'px';
    panel.style.top = (rect.bottom - hostRect.top + 4) + 'px';

    document.addEventListener('mousedown', function handler(event) {
      if (panel.contains(event.target) || anchor.contains(event.target)) {
        return;
      }
      panel.remove();
      document.removeEventListener('mousedown', handler);
    });
  };

  Table.prototype._applyFilter = function (field, values) {
    if (values.length === 0) {
      delete this.filters[field];
    } else {
      this.filters[field] = values;
    }
    this._updateSortIcons();
    this.reload({ keepPage: false });
  };

  Table.prototype._buildQuery = function () {
    var self = this;
    var parts = [];
    parts.push('page=' + this.page);
    parts.push('page_size=' + this.pageSize);
    parts.push('sort_field=' + encodeURIComponent(this.sortField));
    parts.push('sort_order=' + encodeURIComponent(this.sortOrder));
    Object.keys(this.filters).forEach(function (field) {
      var values = self.filters[field] || [];
      values.forEach(function (value) {
        parts.push(encodeURIComponent(field) + '=' + encodeURIComponent(value));
      });
    });
    return parts.join('&');
  };

  Table.prototype.setFilters = function (filters) {
    this.filters = filters || {};
    this._updateSortIcons();
    this.reload({ keepPage: false });
  };

  Table.prototype.reload = function (options) {
    var self = this;
    if (this.loading) {
      return Promise.resolve();
    }
    if (!options || !options.keepPage) {
      this.page = 1;
    }
    this.loading = true;
    this._renderPagination();
    return this.fetchData(this._buildQuery()).then(function (data) {
      self.rows = data.rows || [];
      self.total = data.total || 0;
      self.loading = false;
      self._renderBody();
      self._renderPagination();
      return self._reloadOptions();
    }).catch(function (error) {
      self.loading = false;
      self.rows = [];
      self.total = 0;
      self._renderBody();
      self._renderPagination();
      throw error;
    });
  };

  /* 筛选联动：每个字段的可选项基于「除本字段以外」的当前筛选条件重新计算 */
  Table.prototype._reloadOptions = function () {
    var self = this;
    if (!this.fetchOptions) {
      return Promise.resolve();
    }
    var requests = this.columns.filter(function (column) {
      return column.filterable !== false;
    }).map(function (column) {
      var others = {};
      Object.keys(self.filters).forEach(function (field) {
        if (field !== column.key) {
          others[field] = self.filters[field];
        }
      });
      return self.fetchOptions(column.key, others).then(function (values) {
        self.options[column.key] = values || [];
      }).catch(function () {
        self.options[column.key] = [];
      });
    });
    return Promise.all(requests);
  };

  /* 渲染表体后统一回调，翻页/排序/筛选后外部联动状态才不会残留 */
  Table.prototype._renderBody = function () {
    this._renderRows();
    if (this.onRendered) {
      this.onRendered();
    }
  };

  Table.prototype._renderRows = function () {
    var self = this;
    this.tbody.innerHTML = '';
    if (this.rows.length === 0) {
      this.empty.hidden = false;
      this.table.hidden = true;
      return;
    }
    this.empty.hidden = true;
    this.table.hidden = false;
    this.rows.forEach(function (row, index) {
      var tr = createElement('tr', 'app-table-row');
      tr.dataset.index = String(index);
      if (self.rowClassName) {
        var extraClass = self.rowClassName(row, index);
        if (extraClass) {
          tr.classList.add(extraClass);
        }
      }
      self.columns.forEach(function (column) {
        var td = createElement('td', 'app-table-cell');
        td.dataset.field = column.key;
        if (column.render) {
          var node = column.render(row, index);
          if (typeof node === 'string' || typeof node === 'number') {
            td.textContent = String(node);
          } else if (node) {
            td.appendChild(node);
          }
        } else {
          td.textContent = row[column.key] === undefined || row[column.key] === null
            ? '' : String(row[column.key]);
        }
        tr.appendChild(td);
      });
      if (self.onRowClick) {
        tr.classList.add('app-table-row-clickable');
        tr.addEventListener('click', function (event) {
          self.onRowClick(row, index, event);
        });
      }
      self.tbody.appendChild(tr);
    });
  };

  /* 数字页码：当前页 ± 2 滑动窗口，最多 5 个 */
  Table.prototype._pageNumbers = function () {
    var totalPages = Math.max(1, Math.ceil(this.total / this.pageSize));
    if (totalPages <= MAX_PAGE_BUTTONS) {
      var all = [];
      for (var i = 1; i <= totalPages; i += 1) {
        all.push(i);
      }
      return all;
    }
    var start = this.page - 2;
    var end = this.page + 2;
    if (start < 1) {
      start = 1;
      end = MAX_PAGE_BUTTONS;
    }
    if (end > totalPages) {
      end = totalPages;
      start = totalPages - MAX_PAGE_BUTTONS + 1;
    }
    var pages = [];
    for (var p = start; p <= end; p += 1) {
      pages.push(p);
    }
    return pages;
  };

  Table.prototype._renderPagination = function () {
    var self = this;
    this.pagination.innerHTML = '';
    var totalPages = Math.max(1, Math.ceil(this.total / this.pageSize));

    var totalText = createElement('span', 'app-pagination-total',
      '共 ' + this.total + ' 条');
    totalText.id = this.id + '-pagination-total';
    this.pagination.appendChild(totalText);

    var sizeSelect = createElement('select', 'app-pagination-size');
    sizeSelect.id = this.id + '-page-size';
    PAGE_SIZES.forEach(function (size) {
      var option = document.createElement('option');
      option.value = String(size);
      option.textContent = size + ' 条/页';
      if (size === self.pageSize) {
        option.selected = true;
      }
      sizeSelect.appendChild(option);
    });
    sizeSelect.addEventListener('change', function () {
      self.pageSize = parseInt(sizeSelect.value, 10);
      self.page = 1;
      self.reload({ keepPage: true });
    });
    this.pagination.appendChild(sizeSelect);

    var prev = createElement('button', 'app-pagination-button', '<');
    prev.type = 'button';
    prev.id = this.id + '-page-prev';
    prev.disabled = this.page <= 1;
    prev.addEventListener('click', function () {
      if (self.page > 1) {
        self.page -= 1;
        self.reload({ keepPage: true });
      }
    });
    this.pagination.appendChild(prev);

    this._pageNumbers().forEach(function (pageNumber) {
      var button = createElement('button', 'app-pagination-button', String(pageNumber));
      button.type = 'button';
      button.id = self.id + '-page-' + pageNumber;
      if (pageNumber === self.page) {
        button.classList.add('is-active');
      }
      button.addEventListener('click', function () {
        self.page = pageNumber;
        self.reload({ keepPage: true });
      });
      self.pagination.appendChild(button);
    });

    var next = createElement('button', 'app-pagination-button', '>');
    next.type = 'button';
    next.id = this.id + '-page-next';
    next.disabled = this.page >= totalPages;
    next.addEventListener('click', function () {
      if (self.page < totalPages) {
        self.page += 1;
        self.reload({ keepPage: true });
      }
    });
    this.pagination.appendChild(next);
  };

  global.RtTable = { create: function (config) { return new Table(config); } };
})(window);
