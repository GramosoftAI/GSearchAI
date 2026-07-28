"use client";

import { useEffect, useState } from "react";
import { Modal, Button, Spin, Input, message } from "antd";
import {
  FolderOpenOutlined,
  FileOutlined,
  SearchOutlined,
  CheckOutlined,
  CloudSyncOutlined,
  RightOutlined,
  HomeOutlined,
} from "@ant-design/icons";
import {useSession } from "next-auth/react";

interface Props {
  open: boolean;
  kbId: string;
  token: string;
  onClose: () => void;
  onSuccess?: () => void;
  session : string
}

interface DriveItem {
  id: string;
  name: string;
  isFolder: boolean;
  children?: DriveItem[];
}

export default function SharePointFolderModal({
  open,
  kbId,
  token,
  onClose,
  onSuccess,
  session
}: Props) {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<DriveItem[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const [breadcrumbs, setBreadcrumbs] = useState<{ id: string; name: string }[]>([]);
  const [search, setSearch] = useState("");
  const [expandedFolders, setExpandedFolders] = useState<Record<string, DriveItem[]>>({});
  const [loadingFolders, setLoadingFolders] = useState<string[]>([]);
  const mapItems = (raw: any[]): DriveItem[] =>
    raw.map((item) => ({
      id: item.id,
      name: item.name,
      isFolder: item.is_folder,
    }));

  const loadFiles = async (parentId?: string) => {
    try {
      setLoading(true);
      const url = `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${kbId}/sharepoint/files${
        parentId ? `?parent_id=${parentId}` : ""
      }`;
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}`, accept: "application/json" },
      });
      const data = await res.json();
      setItems(mapItems(data?.data?.items || []));
    } catch (err) {
      console.log(err);
      message.error("Failed to load files");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      loadFiles();
      setBreadcrumbs([]);
      setSearch("");
      setSelectedFiles([]);
      setSelectedFolders([]);
      setExpandedFolders({});
    }
  }, [open]);

  const openFolder = async (folder: DriveItem) => {
    setBreadcrumbs((prev) => [...prev, { id: folder.id, name: folder.name }]);
    setItems([]);
    loadFiles(folder.id);
    setExpandedFolders({});
  };

  const navigateToBreadcrumb = (index: number) => {
    const crumb = breadcrumbs[index];
    setBreadcrumbs((prev) => prev.slice(0, index + 1));
    setItems([]);
    loadFiles(crumb.id);
    setExpandedFolders({});
  };

  const navigateToRoot = () => {
    setBreadcrumbs([]);
    setItems([]);
    loadFiles();
    setExpandedFolders({});
  };

  const toggleExpand = async (folder: DriveItem) => {
    if (expandedFolders[folder.id]) {
      const next = { ...expandedFolders };
      delete next[folder.id];
      setExpandedFolders(next);
      return;
    }
    setLoadingFolders((prev) => [...prev, folder.id]);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${kbId}/sharepoint/files?parent_id=${folder.id}`,
        { headers: { Authorization: `Bearer ${token}`, accept: "application/json" } }
      );
      const data = await res.json();
      setExpandedFolders((prev) => ({
        ...prev,
        [folder.id]: mapItems(data?.data?.items || []),
      }));
    } catch (err) {
      console.log(err);
    } finally {
      setLoadingFolders((prev) => prev.filter((id) => id !== folder.id));
    }
  };

  const toggleItem = (item: DriveItem) => {
    if (item.isFolder) {
      setSelectedFolders((prev) =>
        prev.includes(item.id) ? prev.filter((id) => id !== item.id) : [...prev, item.id]
      );
    } else {
      setSelectedFiles((prev) =>
        prev.includes(item.id) ? prev.filter((id) => id !== item.id) : [...prev, item.id]
      );
    }
  };

  const isSelected = (item: DriveItem) =>
    item.isFolder ? selectedFolders.includes(item.id) : selectedFiles.includes(item.id);
 console.log("asdfghjkl1234567890987623erfghjjbvcxqwertyu")
  const handleSync = async () => {
    try {
      setLoading(true);
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${kbId}/sharepoint/sync`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ file_ids: selectedFiles, folder_ids: selectedFolders,email:session }),
        }
      );
      if (!res.ok) throw new Error("Sync failed");
      message.success("Sharepoint synced successfully");
      onSuccess?.();
      onClose();
    } catch (err) {
      console.log(err);
      message.error("Sync failed");
    } finally {
      setLoading(false);
    }
  };

  const filteredItems = search.trim()
    ? items.filter((i) => i.name.toLowerCase().includes(search.toLowerCase()))
    : items;

  const totalSelected = selectedFiles.length + selectedFolders.length;

  const renderItem = (item: DriveItem, depth = 0) => {
    const selected = isSelected(item);
    const isExpanded = !!expandedFolders[item.id];
    const isLoadingThis = loadingFolders.includes(item.id);
    const children = expandedFolders[item.id] || [];

    return (
      <div key={item.id}>
        <div
          className={`gd-row ${selected ? "gd-row--selected" : ""}`}
          style={{ paddingLeft: `${16 + depth * 24}px` }}
          onClick={() => toggleItem(item)}
          onDoubleClick={() => item.isFolder && openFolder(item)}
        >
          {/* Checkbox */}
          <div
            className={`gd-checkbox ${selected ? "gd-checkbox--checked" : ""}`}
            onClick={(e) => {
              e.stopPropagation();
              toggleItem(item);
            }}
          >
            {selected && <CheckOutlined style={{ fontSize: 11 }} />}
          </div>

          {/* Expand toggle for folders */}
          {item.isFolder && (
            <div
              className="gd-expand"
              onClick={(e) => {
                e.stopPropagation();
                toggleExpand(item);
              }}
            >
              {isLoadingThis ? (
                <Spin size="small" />
              ) : (
                <RightOutlined
                  style={{
                    fontSize: 10,
                    transition: "transform 0.2s",
                    transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)",
                  }}
                />
              )}
            </div>
          )}

          {/* Icon */}
          <div className="gd-icon">
            {item.isFolder ? (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path
                  d="M2 5.5C2 4.67 2.67 4 3.5 4H8.18L9.68 5.5H16.5C17.33 5.5 18 6.17 18 7V15C18 15.83 17.33 16.5 16.5 16.5H3.5C2.67 16.5 2 15.83 2 15V5.5Z"
                  fill="#5F6368"
                />
                <path
                  d="M2 7.5C2 6.67 2.67 6 3.5 6H16.5C17.33 6 18 6.67 18 7.5V15C18 15.83 17.33 16.5 16.5 16.5H3.5C2.67 16.5 2 15.83 2 15V7.5Z"
                  fill="#FBBC04"
                />
              </svg>
            ) : (
              <FileOutlined style={{ color: "#5F6368", fontSize: 18 }} />
            )}
          </div>

          {/* Name */}
          <span className="gd-name">{item.name}</span>

          {/* Open folder hint */}
          {item.isFolder && (
            <span className="gd-hint" onDoubleClick={() => openFolder(item)}>
              Double-click to open
            </span>
          )}
        </div>

        {/* Inline children */}
        {isExpanded &&
          children.map((child) => renderItem(child, depth + 1))}
      </div>
    );
  };

  return (
    <>
      <style>{`
        .gd-modal .ant-modal-content {
          border-radius: 12px;
          padding: 0;
          overflow: hidden;
          font-family: 'Google Sans', 'Roboto', sans-serif;
          box-shadow: 0 8px 40px rgba(0,0,0,0.18);
        }
        .gd-modal .ant-modal-header {
          background: #fff;
          border-bottom: 1px solid #e0e0e0;
          padding: 16px 24px;
          margin: 0;
        }
        .gd-modal .ant-modal-body {
          padding: 0;
        }
        .gd-modal .ant-modal-close {
          top: 14px;
          right: 16px;
          color: #5f6368;
        }

        /* Header */
        .gd-header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 16px 24px;
          border-bottom: 1px solid #e0e0e0;
        }
        .gd-header-title {
          font-size: 18px;
          font-weight: 500;
          color: #202124;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .gd-drive-logo {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        /* Search */
        .gd-search-bar {
          padding: 12px 24px;
          background: #f8f9fa;
          border-bottom: 1px solid #e0e0e0;
        }
        .gd-search-bar .ant-input-affix-wrapper {
          border-radius: 24px;
          background: #fff;
          border: 1px solid #dfe1e5;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08);
          padding: 8px 16px;
        }
        .gd-search-bar .ant-input-affix-wrapper:hover,
        .gd-search-bar .ant-input-affix-wrapper:focus-within {
          border-color: #1a73e8;
          box-shadow: 0 1px 6px rgba(26,115,232,0.2);
        }

        /* Breadcrumb */
        .gd-breadcrumb {
          display: flex;
          align-items: center;
          gap: 2px;
          padding: 8px 24px;
          background: #fff;
          border-bottom: 1px solid #e8eaed;
          font-size: 13px;
          color: #5f6368;
          flex-wrap: wrap;
        }
        .gd-crumb {
          cursor: pointer;
          padding: 4px 8px;
          border-radius: 6px;
          color: #1a73e8;
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 4px;
          transition: background 0.15s;
        }
        .gd-crumb:hover { background: #e8f0fe; }
        .gd-crumb-sep { color: #bdc1c6; font-size: 16px; }
        .gd-crumb-current {
          padding: 4px 8px;
          color: #202124;
          font-weight: 500;
        }

        /* Column headers */
        .gd-col-header {
          display: grid;
          grid-template-columns: 32px 32px 28px 1fr auto;
          gap: 0;
          align-items: center;
          padding: 6px 16px 6px 16px;
          border-bottom: 1px solid #e8eaed;
          background: #f8f9fa;
          font-size: 12px;
          font-weight: 500;
          color: #5f6368;
          letter-spacing: 0.3px;
          text-transform: uppercase;
        }

        /* File list */
        .gd-list {
          height: 420px;
          overflow-y: auto;
          background: #fff;
        }
        .gd-list::-webkit-scrollbar { width: 6px; }
        .gd-list::-webkit-scrollbar-track { background: transparent; }
        .gd-list::-webkit-scrollbar-thumb { background: #dadce0; border-radius: 3px; }

        /* Row */
        .gd-row {
          display: grid;
          grid-template-columns: 32px 28px 28px 1fr auto;
          align-items: center;
          gap: 0;
          padding: 6px 16px;
          cursor: pointer;
          border-bottom: 1px solid #f1f3f4;
          transition: background 0.1s;
          user-select: none;
        }
        .gd-row:hover { background: #f1f3f4; }
        .gd-row--selected { background: #e8f0fe !important; }
        .gd-row--selected .gd-name { color: #1a73e8; }

        /* Checkbox */
        .gd-checkbox {
          width: 18px;
          height: 18px;
          border: 2px solid #dadce0;
          border-radius: 3px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.15s;
          flex-shrink: 0;
          color: #fff;
        }
        .gd-checkbox:hover { border-color: #1a73e8; }
        .gd-checkbox--checked {
          background: #1a73e8;
          border-color: #1a73e8;
        }

        /* Expand */
        .gd-expand {
          width: 24px;
          height: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 50%;
          color: #5f6368;
          transition: background 0.15s;
          flex-shrink: 0;
        }
        .gd-expand:hover { background: #e8eaed; }

        .gd-icon {
          width: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

      .gd-name {
          font-size: 14px;
          color: #202124;
          padding-left: 8px;

          white-space: nowrap;     /* single line */
          overflow: hidden;
          text-overflow: ellipsis;
          min-width: 250px;        /* important */
        }
        .gd-hint {
          font-size: 11px;
          color: #bdc1c6;
          padding-right: 4px;
          display: none;
          white-space: nowrap;
        }
        .gd-row:hover .gd-hint { display: block; }

        /* Footer */
        .gd-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 24px;
          background: #f8f9fa;
          border-top: 1px solid #e0e0e0;
        }
        .gd-selection-info {
          font-size: 13px;
          color: #5f6368;
        }
        .gd-selection-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: #e8f0fe;
          color: #1a73e8;
          font-weight: 600;
          padding: 2px 10px;
          border-radius: 12px;
          font-size: 13px;
        }
        .gd-btn-cancel {
          border: 1px solid #dadce0 !important;
          color: #3c4043 !important;
          border-radius: 6px !important;
          height: 36px !important;
          font-weight: 500 !important;
          font-size: 14px !important;
        }
        .gd-btn-cancel:hover {
          background: #f1f3f4 !important;
          border-color: #c6c6c6 !important;
        }
        .gd-btn-sync {
          background: #1a73e8 !important;
          border-color: #1a73e8 !important;
          color: #fff !important;
          border-radius: 6px !important;
          height: 36px !important;
          font-weight: 500 !important;
          font-size: 14px !important;
          display: flex !important;
          align-items: center !important;
          gap: 6px !important;
        }
        .gd-btn-sync:hover {
          background: #1557b0 !important;
          border-color: #1557b0 !important;
        }
        .gd-btn-sync:disabled {
          background: #c6c6c6 !important;
          border-color: #c6c6c6 !important;
        }

        .gd-empty {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: #bdc1c6;
          gap: 12px;
        }
        .gd-empty svg { opacity: 0.4; }
      `}</style>

      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        width={780}
        destroyOnClose
        className="gd-modal"
        title={null}
        closable
      >
        {/* Header */}
        <div className="gd-header">
          <div className="gd-drive-logo">
            {/* Google Drive logo colors */}
            <svg width="28" height="24" viewBox="0 0 87.3 78" fill="none">
              <path d="M6.6 66.85l3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3L27.5 53H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066DA"/>
              <path d="M43.65 25L29.9 1.4c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0-1.2 4.5h27.5z" fill="#00AC47"/>
              <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8l5.85 10.9z" fill="#EA4335"/>
              <path d="M43.65 25L57.4 1.4C56.05.6 54.5.2 52.9.2H34.4c-1.6 0-3.15.4-4.5 1.2z" fill="#00832D"/>
              <path d="M59.8 53H27.5L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.4 4.5-1.2z" fill="#2684FC"/>
              <path d="M73.4 26.5l-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3L43.65 25 59.8 53h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#FFBA00"/>
            </svg>
            <span className="gd-header-title">Sharepoint</span>
          </div>
        </div>

        {/* Search */}
        <div className="gd-search-bar">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search in Drive"
            prefix={<SearchOutlined style={{ color: "#9aa0a6" }} />}
            allowClear
          />
        </div>

        {/* Breadcrumb */}
        <div className="gd-breadcrumb">
          <span className="gd-crumb" onClick={navigateToRoot}>
            <HomeOutlined />
            My Drive
          </span>
          {breadcrumbs.map((crumb, i) => (
            <span key={crumb.id} style={{ display: "flex", alignItems: "center", gap: 2 }}>
              <span className="gd-crumb-sep">›</span>
              {i === breadcrumbs.length - 1 ? (
                <span className="gd-crumb-current">{crumb.name}</span>
              ) : (
                <span className="gd-crumb" onClick={() => navigateToBreadcrumb(i)}>
                  {crumb.name}
                </span>
              )}
            </span>
          ))}
        </div>

        {/* Column header */}
        <div className="gd-col-header">
          <span />
          <span />
          <span />
          <span>Name</span>
          <span style={{ paddingRight: 4 }}>Action</span>
        </div>

        {/* File list */}
        <div className="gd-list">
          {loading ? (
            <div className="gd-empty">
              <Spin size="large" />
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="gd-empty">
              <FolderOpenOutlined style={{ fontSize: 48 }} />
              <span style={{ fontSize: 14 }}>
                {search ? "No matching files" : "This folder is empty"}
              </span>
            </div>
          ) : (
            [...filteredItems]
              .sort((a, b) => {
                if (a.isFolder && !b.isFolder) return -1;
                if (!a.isFolder && b.isFolder) return 1;
                return a.name.localeCompare(b.name);
              })
              .map((item) => renderItem(item))
          )}
        </div>

        {/* Footer */}
        <div className="gd-footer">
          <div className="gd-selection-info">
            {totalSelected > 0 ? (
              <span>
                <span className="gd-selection-badge">{totalSelected} selected</span>
                &nbsp;&nbsp;
                <span style={{ fontSize: 12 }}>
                  {selectedFiles.length} file{selectedFiles.length !== 1 ? "s" : ""},{" "}
                  {selectedFolders.length} folder{selectedFolders.length !== 1 ? "s" : ""}
                </span>
              </span>
            ) : (
              <span>Select files or folders to sync</span>
            )}
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <Button className="gd-btn-cancel" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="gd-btn-sync"
              onClick={handleSync}
              loading={loading}
              disabled={totalSelected === 0}
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