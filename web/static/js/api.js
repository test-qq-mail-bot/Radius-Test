/* HTTP 接口客户端。
 *
 * 约定：
 *   1. 全部接口前缀 /api；
 *   2. 失败时返回 {success:false, message:'...'}，由页面统一提示；
 *   3. 不做任何外网请求，保证完全离线可运行。
 */
(function (global) {
  'use strict';

  function request(method, path, body, options) {
    var config = { method: method, headers: {} };
    if (body !== undefined && body !== null && !(body instanceof FormData)) {
      config.headers['Content-Type'] = 'application/json';
      config.body = JSON.stringify(body);
    } else if (body instanceof FormData) {
      config.body = body;
    }
    if (options && options.formData) {
      config.body = options.formData;
    }
    return fetch(path, config).then(function (response) {
      var contentType = response.headers.get('content-type') || '';
      if (!response.ok) {
        return response.json().catch(function () {
          return { detail: '请求失败，状态码 ' + response.status };
        }).then(function (data) {
          throw new Error(data.detail || data.message || ('请求失败，状态码 ' + response.status));
        });
      }
      if (contentType.indexOf('application/json') >= 0) {
        return response.json();
      }
      return response.text();
    });
  }

  var API = {
    get: function (path) {
      return request('GET', path);
    },
    post: function (path, body) {
      return request('POST', path, body);
    },
    put: function (path, body) {
      return request('PUT', path, body);
    },
    del: function (path) {
      return request('DELETE', path);
    },
    upload: function (path, formData) {
      return fetch(path, { method: 'POST', body: formData }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) {
            throw new Error(data.detail || data.message || '上传失败');
          }
          return data;
        });
      });
    },
    downloadUrl: function (path) {
      return path;
    },

    systemInfo: function () {
      return this.get('/api/system/info');
    },
    systemStats: function () {
      return this.get('/api/system/stats');
    },
    getConfig: function () {
      return this.get('/api/config');
    },
    saveConfig: function (payload) {
      return this.put('/api/config', payload);
    },
    listServers: function () {
      return this.get('/api/servers');
    },
    createServer: function (payload) {
      return this.post('/api/servers', payload);
    },
    updateServer: function (name, payload) {
      return this.put('/api/servers/' + encodeURIComponent(name), payload);
    },
    deleteServer: function (name) {
      return this.del('/api/servers/' + encodeURIComponent(name));
    },
    testServer: function (name) {
      return this.post('/api/servers/' + encodeURIComponent(name) + '/test');
    },
    testUserAuth: function (name, payload) {
      return this.post('/api/servers/' + encodeURIComponent(name) + '/auth-test', payload);
    },
    batchAuthTest: function (server, usernames, protocol) {
      return this.post('/api/servers/' + encodeURIComponent(server) + '/batch-auth-test', {
        usernames: usernames,
        protocol: protocol || 'pap'
      });
    },
    listUsers: function () {
      return this.get('/api/users');
    },
    batchDeleteUsers: function (usernames) {
      return this.post('/api/users/batch-delete', { usernames: usernames });
    },
    createUser: function (payload) {
      return this.post('/api/users', payload);
    },
    updateUser: function (username, payload) {
      return this.put('/api/users/' + encodeURIComponent(username), payload);
    },
    deleteUser: function (username) {
      return this.del('/api/users/' + encodeURIComponent(username));
    },
    /* 导入用户 CSV。
       参数可以是 File/Blob，也可以是 CSV 文本（内部自动包装为 import.csv）。
       导入规则由后端统一处理：用户名唯一键、一律覆盖、密码留空代表不修改。 */
    importUsers: function (fileOrText) {
      var file = fileOrText;
      if (typeof fileOrText === 'string') {
        file = new File([fileOrText], 'import.csv', { type: 'text/csv' });
      }
      var form = new FormData();
      form.append('file', file);
      return this.upload('/api/users/import', form);
    },
    listTemplates: function () {
      return this.get('/api/dictionaries');
    },
    listLocalAddresses: function () {
      return this.get('/api/system/addresses');
    },
    getTemplate: function (name) {
      return this.get('/api/dictionaries/' + encodeURIComponent(name));
    },
    deriveTemplate: function (payload) {
      return this.post('/api/dictionaries/derive', payload);
    },
    deleteTemplate: function (name) {
      return this.del('/api/dictionaries/' + encodeURIComponent(name));
    },
    uploadTemplate: function (file) {
      var form = new FormData();
      form.append('file', file);
      return this.upload('/api/dictionaries/upload', form);
    },
    reloadTemplates: function () {
      return this.post('/api/dictionaries/reload', {});
    },
    currentTask: function () {
      return this.get('/api/tasks/current');
    },
    startTask: function (payload) {
      return this.post('/api/tasks', payload);
    },
    stopTask: function (taskId) {
      return this.post('/api/tasks/' + encodeURIComponent(taskId) + '/stop');
    },
    heartbeat: function () {
      return this.post('/api/tasks/heartbeat', {});
    },
    queryResults: function (params) {
      return this.get('/api/results?' + params);
    },
    resultFilters: function (params) {
      return this.get('/api/results/filters' + (params ? ('?' + params) : ''));
    },
    resultDetail: function (id) {
      return this.get('/api/results/' + id);
    },
    listSessions: function (params) {
      return this.get('/api/sessions?' + params);
    },
    listPackets: function (params) {
      return this.get('/api/packets?' + params);
    },
    packetDetail: function (id) {
      return this.get('/api/packets/' + id);
    },
    clearResults: function () {
      return this.post('/api/results/clear', {});
    }
  };

  global.RtApi = API;
})(window);
