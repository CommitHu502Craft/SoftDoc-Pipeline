import React, { useState, useEffect } from 'react';
import { accountApi, Account } from '../api';
import '../styles/AccountsPage.css';

export const AccountsPage: React.FC = () => {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    description: '',
  });

  // 加载账号列表
  const loadAccounts = async () => {
    setLoading(true);
    try {
      const response = await accountApi.list();
      setAccounts(response.accounts);
    } catch (error) {
      console.error('加载账号失败:', error);
      alert('加载账号失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAccounts();
  }, []);

  // 处理添加/编辑账号
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      if (editingAccount) {
        // 更新账号
        await accountApi.update(editingAccount.id, formData);
        alert('账号更新成功');
      } else {
        // 添加新账号
        await accountApi.create(formData);
        alert('账号添加成功');
      }

      setShowAddModal(false);
      setEditingAccount(null);
      setFormData({ username: '', password: '', description: '' });
      loadAccounts();
    } catch (error) {
      console.error('保存账号失败:', error);
      alert('保存账号失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 处理删除账号
  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除此账号吗？')) return;

    setLoading(true);
    try {
      await accountApi.delete(id);
      alert('账号删除成功');
      loadAccounts();
    } catch (error) {
      console.error('删除账号失败:', error);
      alert('删除账号失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 打开编辑模态框
  const handleEdit = (account: Account) => {
    setEditingAccount(account);
    setFormData({
      username: account.username,
      password: '',
      description: account.description,
    });
    setShowAddModal(true);
  };

  // 打开添加模态框
  const handleAdd = () => {
    setEditingAccount(null);
    setFormData({ username: '', password: '', description: '' });
    setShowAddModal(true);
  };

  return (
    <div className="accounts-page">
      <div className="page-header">
        <h1>账号管理</h1>
        <button className="btn btn-primary" onClick={handleAdd} disabled={loading}>
          + 添加账号
        </button>
      </div>

      <div className="accounts-list">
        {loading && accounts.length === 0 ? (
          <div className="loading">加载中...</div>
        ) : accounts.length === 0 ? (
          <div className="empty-state">
            <p>暂无账号，点击上方"添加账号"按钮创建第一个账号</p>
          </div>
        ) : (
          <table className="accounts-table">
            <thead>
              <tr>
                <th>用户名</th>
                <th>说明</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.id}>
                  <td>{account.username}</td>
                  <td>{account.description || '-'}</td>
                  <td>{account.created_at}</td>
                  <td>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => handleEdit(account)}
                      disabled={loading}
                    >
                      编辑
                    </button>
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => handleDelete(account.id)}
                      disabled={loading}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 添加/编辑账号模态框 */}
      {showAddModal && (
        <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>{editingAccount ? '编辑账号' : '添加账号'}</h2>
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>用户名 *</label>
                <input
                  type="text"
                  value={formData.username}
                  onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  required
                  placeholder="请输入用户名"
                />
              </div>

              <div className="form-group">
                <label>密码 {editingAccount ? '(留空则不修改)' : '*'}</label>
                <input
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  required={!editingAccount}
                  placeholder="请输入密码"
                />
              </div>

              <div className="form-group">
                <label>说明</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="请输入账号说明（可选）"
                  rows={3}
                />
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowAddModal(false)}
                  disabled={loading}
                >
                  取消
                </button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? '保存中...' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
