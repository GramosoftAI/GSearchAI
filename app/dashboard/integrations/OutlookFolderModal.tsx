"use client";

import { useEffect, useState } from "react";
import { Modal, Button, Spin, Input, Progress, Typography } from "antd";
import {
  FolderOpenOutlined,
  SearchOutlined,
  CheckOutlined,
  CloudSyncOutlined,
  MailOutlined
} from "@ant-design/icons";
import { toast } from "react-hot-toast";
import { getCookie } from "../../config/cookies";

const { Text } = Typography;

interface Props {
  open: boolean;
  kbId: string;
  onClose: () => void;
  onSuccess?: (payload: any) => void;
  session: string;
  agentName: string;
}

interface MailFolder {
  id: string;
  name: string;
  itemCount: number;
  unreadCount: number;
}

const mockMailFolders: MailFolder[] = [
  { id: "inbox", name: "Inbox", itemCount: 1240, unreadCount: 12 },
  { id: "sent", name: "Sent Items", itemCount: 512, unreadCount: 0 },
  { id: "drafts", name: "Drafts", itemCount: 18, unreadCount: 0 },
  { id: "archive", name: "Archive", itemCount: 2840, unreadCount: 0 },
  { id: "junk", name: "Junk Email", itemCount: 85, unreadCount: 20 },
  { id: "deleted", name: "Deleted Items", itemCount: 142, unreadCount: 0 },
];

export default function OutlookFolderModal({
  open,
  kbId,
  onClose,
  onSuccess,
  session,
  agentName
}: Props) {
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState(0);
  const [search, setSearch] = useState("");
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);

  useEffect(() => {
    if (open) {
      setSearch("");
      setSelectedFolders([]);
      setSyncing(false);
      setSyncProgress(0);
    }
  }, [open]);

  const toggleFolder = (folderId: string) => {
    setSelectedFolders((prev) =>
      prev.includes(folderId) ? prev.filter((id) => id !== folderId) : [...prev, folderId]
    );
  };

  const handleSync = () => {
    if (selectedFolders.length === 0) {
      toast.error("Please select at least one folder to sync");
      return;
    }

    setSyncing(true);
    setSyncProgress(0);

    const performSync = async () => {
      const token = getCookie("AUTH_TOKEN") || "";
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${kbId}/outlook/sync`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ folder_ids: selectedFolders, email: session }),
          }
        );
        if (!res.ok) throw new Error("Sync failed");

        let progress = 0;
        const interval = setInterval(() => {
          progress += 20;
          setSyncProgress(progress);
          if (progress >= 100) {
            clearInterval(interval);
            setSyncing(false);
            toast.success("Outlook folders synchronized successfully!");
            onSuccess?.({ folder_ids: selectedFolders, email: session });
            onClose();
          }
        }, 150);
      } catch (err) {
        console.error(err);
        toast.error("Outlook sync failed");
        setSyncing(false);
      }
    };

    performSync();
  };

  const filteredFolders = search.trim()
    ? mockMailFolders.filter((f) => f.name.toLowerCase().includes(search.toLowerCase()))
    : mockMailFolders;

  const isAllSelected = filteredFolders.length > 0 && filteredFolders.every((f) => selectedFolders.includes(f.id));

  const toggleSelectAll = () => {
    if (isAllSelected) {
      const filteredIds = filteredFolders.map((f) => f.id);
      setSelectedFolders((prev) => prev.filter((id) => !filteredIds.includes(id)));
    } else {
      const filteredIds = filteredFolders.map((f) => f.id);
      setSelectedFolders((prev) => [...new Set([...prev, ...filteredIds])]);
    }
  };

  return (
    <>
      <style>{`
        .ol-modal .ant-modal-content {
          border-radius: 20px;
          padding: 0;
          overflow: hidden;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          box-shadow: 0 10px 40px rgba(0,0,0,0.12);
        }
        .ol-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 20px 24px;
          background: #f3f2f1;
          border-bottom: 1px solid #edebe9;
        }
        .ol-header-title {
          font-size: 16px;
          font-weight: 600;
          color: #323130;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .ol-search-bar {
          padding: 12px 24px;
          background: #faf9f8;
          border-bottom: 1px solid #edebe9;
        }
        .ol-search-bar .ant-input-affix-wrapper {
          border-radius: 8px;
          border: 1px solid #d2d0ce;
          padding: 6px 12px;
        }
        .ol-search-bar .ant-input-affix-wrapper:hover,
        .ol-search-bar .ant-input-affix-wrapper:focus-within {
          border-color: #0078d4;
        }
        .ol-col-header {
          display: grid;
          grid-template-columns: 48px 1fr 120px 120px;
          align-items: center;
          padding: 10px 24px;
          border-bottom: 1px solid #edebe9;
          background: #f3f2f1;
          font-size: 11px;
          font-weight: 600;
          color: #605e5c;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .ol-list {
          height: 300px;
          overflow-y: auto;
          background: #fff;
        }
        .ol-row {
          display: grid;
          grid-template-columns: 48px 1fr 120px 120px;
          align-items: center;
          padding: 12px 24px;
          cursor: pointer;
          border-bottom: 1px solid #f3f2f1;
          transition: background 0.15s;
          user-select: none;
        }
        .ol-row:hover { background: #faf9f8; }
        .ol-row--selected { background: #eff6fc !important; }
        .ol-row--selected .ol-name { color: #0078d4; font-weight: 600; }
        .ol-checkbox {
          width: 16px;
          height: 16px;
          border: 1px solid #8a8886;
          border-radius: 2px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.1s;
          background: #fff;
          color: #fff;
        }
        .ol-checkbox--checked {
          background: #0078d4;
          border-color: #0078d4;
        }
        .ol-name {
          font-size: 14px;
          color: #323130;
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .ol-meta {
          font-size: 13px;
          color: #605e5c;
        }
        .ol-unread {
          color: #0078d4;
          font-weight: 600;
        }
        .ol-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 24px;
          background: #f3f2f1;
          border-top: 1px solid #edebe9;
        }
        .ol-btn-cancel {
          border: 1px solid #8a8886 !important;
          color: #323130 !important;
          border-radius: 4px !important;
          font-weight: 600 !important;
        }
        .ol-btn-sync {
          background: #0078d4 !important;
          border-color: #0078d4 !important;
          color: #fff !important;
          border-radius: 4px !important;
          font-weight: 600 !important;
        }
        .ol-btn-sync:hover {
          background: #106ebe !important;
          border-color: #106ebe !important;
        }
      `}</style>

      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        width={700}
        destroyOnClose
        className="ol-modal"
        title={null}
        closable
      >
        {/* Header */}
        <div className="ol-header">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M21 5.5V18.5C21 19.88 19.88 21 18.5 21H5.5C4.12 21 3 19.88 3 18.5V5.5C3 4.12 4.12 3 5.5 3H18.5C19.88 3 21 4.12 21 5.5Z" fill="#0078D4"/>
            <path d="M18.5 4.5L12 9.5L5.5 4.5V6L12 11.5L18.5 6V4.5Z" fill="white"/>
          </svg>
          <span className="ol-header-title">Outlook Integration Setup ({agentName})</span>
        </div>

        {/* Search */}
        <div className="ol-search-bar">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search mail folders..."
            prefix={<SearchOutlined style={{ color: "#8a8886" }} />}
            allowClear
          />
        </div>

        {/* Sync Progress Banner */}
        {syncing && (
          <div className="px-6 py-4 bg-[#eff6fc] border-b border-[#edebe9]">
            <div className="flex justify-between items-center mb-1.5 text-xs text-[#0078d4] font-semibold">
              <span>Syncing Outlook folders into agent cognitive memory...</span>
              <span>{syncProgress}%</span>
            </div>
            <Progress percent={syncProgress} showInfo={false} strokeColor="#0078d4" />
          </div>
        )}

        {/* Column Headers */}
        <div className="ol-col-header">
          <div
            className={`ol-checkbox ${isAllSelected ? "ol-checkbox--checked" : ""}`}
            onClick={toggleSelectAll}
            style={{ cursor: "pointer" }}
          >
            {isAllSelected && <CheckOutlined style={{ fontSize: 9 }} />}
          </div>
          <span>Folder Name</span>
          <span>Total Mails</span>
          <span>Unread Mails</span>
        </div>

        {/* Folder List */}
        <div className="ol-list">
          {loading ? (
            <div className="flex justify-center items-center h-full">
              <Spin />
            </div>
          ) : filteredFolders.length === 0 ? (
            <div className="flex flex-col justify-center items-center h-full text-slate-400 gap-2">
              <MailOutlined style={{ fontSize: 36 }} />
              <span>No matching folders found</span>
            </div>
          ) : (
            filteredFolders.map((folder) => {
              const isSelected = selectedFolders.includes(folder.id);
              return (
                <div
                  key={folder.id}
                  className={`ol-row ${isSelected ? "ol-row--selected" : ""}`}
                  onClick={() => toggleFolder(folder.id)}
                >
                  <div
                    className={`ol-checkbox ${isSelected ? "ol-checkbox--checked" : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleFolder(folder.id);
                    }}
                  >
                    {isSelected && <CheckOutlined style={{ fontSize: 9 }} />}
                  </div>
                  <span className="ol-name">
                    <FolderOpenOutlined style={{ color: isSelected ? "#0078d4" : "#605e5c" }} />
                    {folder.name}
                  </span>
                  <span className="ol-meta">{folder.itemCount.toLocaleString()}</span>
                  <span className={`ol-meta ${folder.unreadCount > 0 ? "ol-unread" : ""}`}>
                    {folder.unreadCount > 0 ? folder.unreadCount.toLocaleString() : "—"}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="ol-footer">
          <span className="text-xs text-[#605e5c]">
            {selectedFolders.length > 0 ? (
              <span>Selected <strong>{selectedFolders.length}</strong> folder(s) to synchronize</span>
            ) : (
              "Select Outlook mailboxes to register"
            )}
          </span>

          <div style={{ display: "flex", gap: 10 }}>
            <Button className="ol-btn-cancel" onClick={onClose} disabled={syncing}>
              Cancel
            </Button>
            <Button
              className="ol-btn-sync"
              onClick={handleSync}
              loading={syncing}
              disabled={selectedFolders.length === 0 || syncing}
              icon={<CloudSyncOutlined />}
            >
              Sync Selected
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
