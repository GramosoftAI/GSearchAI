(function () {
  if (window.__gragWidgetInitialized) return;
  const script = document.currentScript;
  if (!script) return;
  window.__gragWidgetInitialized = true;
  const agentId = script.getAttribute("data-agent-id");
  const tenantId = script.getAttribute("data-tenant-id");

  // Dynamically detect base URL of the hosting widget
  let baseUrl = "";
  try {
    const scriptSrc = script.getAttribute("src");
    if (scriptSrc && scriptSrc.startsWith("http")) {
      const url = new URL(scriptSrc);
      baseUrl = url.origin;
    } else {
      baseUrl = window.location.origin;
    }
  } catch (e) {
    console.error("GragWidget: Error parsing script URL, falling back.", e);
  }

  const targetAgentId = agentId || "24b3d80f-aed6-4b70-b5b2-48c64cb616c1";
  const apiHost = "https://uat.gramosoft.tech";
  const cleanApiHost = apiHost.endsWith("/api/v1") ? apiHost : apiHost + "/api/v1";
  const configApiUrl = `${cleanApiHost}/embed/configs/${targetAgentId}${tenantId ? `?tenant_id=${tenantId}` : ""}`;

  fetch(configApiUrl)
    .then(res => res.json())
    .then(response => {
      const config = (response && response.success && response.data) ? response.data : {};
      initWidget(config);
    })
    .catch(err => {
      console.warn("GragWidget: Failed to fetch embed config, falling back to script attributes.", err);
      initWidget({});
    });

  function initWidget(config) {
    const chatType = config.chat_type || script.getAttribute("data-chat-type") || "icon"; // "icon" or "search"
    const position = config.position || script.getAttribute("data-position") || "center"; // "center" or "right"
    const placeholder = config.placeholder_text || script.getAttribute("data-placeholder") || "Ask about anything...";
    const themeColor = config.theme_color || script.getAttribute("data-theme-color") || "#0fb5a1";

    // Custom design & branding attributes
    const headerLogoAttr = config.header_logo !== undefined ? config.header_logo : script.getAttribute("data-header-logo");
    const headerLogo = headerLogoAttr !== null && headerLogoAttr !== undefined ? headerLogoAttr : "/512_512.png";
    const headerAlign = config.header_align || script.getAttribute("data-header-align") || "center";
    const headerNameAttr = config.header_name !== undefined ? config.header_name : script.getAttribute("data-header-name");
    const headerName = headerNameAttr !== null ? headerNameAttr : "Gsearch AI";
    const headerSubtextAttr = config.header_subtext !== undefined ? config.header_subtext : script.getAttribute("data-header-subtext");
    const headerSubtext = headerSubtextAttr !== null ? headerSubtextAttr : "The team can also help";
    const agentLabelAttr = config.agent_label !== undefined ? config.agent_label : script.getAttribute("data-agent-label");
    const agentLabel = agentLabelAttr !== null ? agentLabelAttr : "Agent";
    const themeTextColor = config.theme_text_color || script.getAttribute("data-theme-text-color") || "#ffffff";
    const btnBgColorAttr = config.btn_bg_color !== undefined ? config.btn_bg_color : script.getAttribute("data-btn-bg-color");
    const btnBgColor = btnBgColorAttr !== null ? btnBgColorAttr : themeColor;
    const btnBorderColorAttr = config.btn_border_color !== undefined ? config.btn_border_color : script.getAttribute("data-btn-border-color");
    const btnBorderColor = btnBorderColorAttr !== null ? btnBorderColorAttr : btnBgColor;
    const botAvatar = config.bot_avatar || script.getAttribute("data-bot-avatar") || "";
    const buttonIcon = config.button_icon || script.getAttribute("data-button-icon") || "";
    const buttonAlign = config.button_align || script.getAttribute("data-button-align") || "right";
    const showButtonText = (config.show_button_text !== undefined && config.show_button_text !== null) ? config.show_button_text : (script.getAttribute("data-show-button-text") === "true");
    const buttonText = config.button_text || script.getAttribute("data-button-text") || "";
    const initialMessage = config.initial_message || script.getAttribute("data-initial-message") || "";
    const displaySources = (config.display_sources !== undefined && config.display_sources !== null) ? config.display_sources : (script.getAttribute("data-display-sources") || "true");
    const allowDownloads = (config.allow_downloads !== undefined && config.allow_downloads !== null) ? config.allow_downloads : (script.getAttribute("data-allow-downloads") || "false");
    const displayCopy = (config.display_copy !== undefined && config.display_copy !== null) ? config.display_copy : (script.getAttribute("data-display-copy") || "true");
    const displayFeedback = (config.display_feedback !== undefined && config.display_feedback !== null) ? config.display_feedback : (script.getAttribute("data-display-feedback") || "true");
    const linkSafety = (config.link_safety !== undefined && config.link_safety !== null) ? config.link_safety : (script.getAttribute("data-link-safety") || "false");

    let buttonBottom = config.button_bottom || script.getAttribute("data-button-bottom") || "20px";
    if (buttonBottom && !isNaN(Number(buttonBottom))) {
      buttonBottom = buttonBottom + "px";
    }

    let userInteracted = false;
    const setInteracted = () => {
      userInteracted = true;
      window.removeEventListener("mousedown", setInteracted, { capture: true });
      window.removeEventListener("keydown", setInteracted, { capture: true });
    };
    window.addEventListener("mousedown", setInteracted, { capture: true });
    window.addEventListener("keydown", setInteracted, { capture: true });

    // Lead Collection & Support Escalation Attributes
    const leadCollection = (config.lead_collection !== undefined && config.lead_collection !== null) ? config.lead_collection : (script.getAttribute("data-lead-collection") || "false");
    const leadFields = (Array.isArray(config.lead_fields) ? config.lead_fields.join(",") : config.lead_fields) || script.getAttribute("data-lead-fields") || "";
    const leadTiming = config.lead_timing || script.getAttribute("data-lead-timing") || "pre-chat";
    const escalationEnabled = (config.escalation_enabled !== undefined && config.escalation_enabled !== null) ? config.escalation_enabled : (script.getAttribute("data-escalation-enabled") || "false");
    const escalationLink = config.escalation_link || script.getAttribute("data-escalation-link") || "";

    const toProxyUrl = (url) => {
      if (!url) return url;
      const cleanUrl = url.split("?")[0];
      const s3Match = cleanUrl.match(/amazonaws\.com\/grag\/logos\/(.+)/);
      if (s3Match) {
        return `${baseUrl.endsWith("/api/v1") ? baseUrl : baseUrl + "/api/v1"}/embed/logo/render/${s3Match[1]}`;
      }
      if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("blob:") || url.startsWith("data:")) {
        return url;
      }
      const proxyMatch = cleanUrl.match(/\/embed\/logo\/render\/(.+)/);
      if (proxyMatch) {
        return `${baseUrl.endsWith("/api/v1") ? baseUrl : baseUrl + "/api/v1"}/embed/logo/render/${proxyMatch[1]}`;
      }
      return url;
    };

    const resolvedHeaderLogo = toProxyUrl(headerLogo);
    const resolvedBotAvatar = toProxyUrl(botAvatar);
    const resolvedButtonIcon = toProxyUrl(buttonIcon);

    // --- Style Elements (Keyframes & Animations) ---
    const styleEl = document.createElement("style");
    styleEl.innerHTML = `
      .grag-iframe-container {
        position: fixed !important;
        border: none !important;
        background: transparent !important;
        border-radius: 24px;
        z-index: 2147483647 !important;
        opacity: 0;
        visibility: hidden;
        transform: scale(0.05);
        transition: opacity 0.22s cubic-bezier(0.25, 1, 0.5, 1), 
                    transform 0.25s cubic-bezier(0.25, 1, 0.5, 1), 
                    visibility 0.25s,
                    left 0.28s cubic-bezier(0.25, 1, 0.5, 1),
                    top 0.28s cubic-bezier(0.25, 1, 0.5, 1);
        will-change: transform, opacity, left, top;
        isolation: isolate;
      }
      .grag-iframe-container.show {
        visibility: visible;
        opacity: 1;
        transform: scale(1);
        /* macOS-style spring bounce launch animation */
        transition: opacity 0.25s cubic-bezier(0.16, 1, 0.3, 1), transform 0.38s cubic-bezier(0.34, 1.56, 0.64, 1);
      }
      .grag-iframe-container.dragging-active {
        pointer-events: none !important;
        transition: none !important;
      }
      @media (min-width: 641px) {
        .grag-iframe-container.center-search {
          transform: translateX(-50%) scale(0.05);
        }
        .grag-iframe-container.center-search.show {
          transform: translateX(-50%) scale(1);
        }
      }

      /* Disable scaling transforms on search mode iframe container */
      .grag-iframe-container.search-mode {
        transform: none !important;
        transition: opacity 0.08s ease-in-out, visibility 0.08s !important;
      }
      .grag-iframe-container.search-mode.show {
        transform: none !important;
        transition: opacity 0.08s ease-in-out, visibility 0.08s !important;
      }
      @media (min-width: 641px) {
        .grag-iframe-container.search-mode.center-search {
          transform: translateX(-50%) !important;
        }
        .grag-iframe-container.search-mode.center-search.show {
          transform: translateX(-50%) !important;
        }
      }

      /* Search Bar Wrapper Coordinated transitions */
      .grag-search-wrapper {
        position: fixed !important;
        z-index: 999998 !important;
        box-sizing: border-box !important;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
        transition: opacity 0.08s ease-in-out;
        will-change: opacity;
        padding: 0 8px !important;
      }
      .grag-search-wrapper.layout-center {
        bottom: 40px;
        left: 50%;
        right: auto;
        transform: translateX(-50%) scale(1);
        width: 90%;
        max-width: 680px;
      }
      .grag-search-wrapper.layout-right {
        bottom: 40px;
        right: 40px;
        left: auto;
        transform: scale(1);
        width: 90%;
        max-width: 420px;
      }
      @media (max-width: 640px) {
        .grag-search-wrapper.layout-center,
        .grag-search-wrapper.layout-right {
          left: 16px !important;
          right: 16px !important;
          transform: none !important;
          width: calc(100% - 32px) !important;
          bottom: 32px !important;
        }
      }

      /* Hidden transitions */
      .grag-search-wrapper.layout-center.hidden {
        opacity: 0 !important;
        transform: translateX(-50%) !important;
        pointer-events: none !important;
      }
      .grag-search-wrapper.layout-right.hidden {
        opacity: 0 !important;
        transform: none !important;
        pointer-events: none !important;
      }
      @media (max-width: 640px) {
        .grag-search-wrapper.layout-center.hidden,
        .grag-search-wrapper.layout-right.hidden {
          transform: none !important;
        }
      }
      .grag-search-glow {
        padding: 2px;
        border-radius: 26px;
        background: linear-gradient(90deg, ${themeColor}, ${themeColor}ee, #ffffff, ${themeColor}ee, ${themeColor});
        background-size: 300% 100%;
        animation: borderShift 3s ease infinite;
        box-shadow: 0 4px 16px ${themeColor}30;
        transition: box-shadow 0.3s ease;
      }
      .grag-search-glow.active, .grag-search-glow:hover {
        box-shadow: 0 6px 24px ${themeColor}50;
      }
      @keyframes borderShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
      }
      .grag-icon-btn {
        position: fixed;
        bottom: ${buttonBottom};
        ${buttonAlign === "left" ? "left: 20px; right: auto;" : "right: 20px; left: auto;"}
        min-width: 60px;
        height: 60px;
        border-radius: 50%;
        cursor: pointer;
        background: ${btnBgColor};
        border: 2px solid ${btnBorderColor};
        box-shadow: 0 6px 20px ${btnBgColor}40;
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 999999;
        transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), box-shadow 0.3s ease;
        animation: floatPulse 3s ease-in-out infinite;
      }
      .grag-icon-btn:hover {
        transform: scale(1.05) !important;
        box-shadow: 0 10px 30px ${themeColor}65;
      }
      @keyframes floatPulse {
        0%, 100% {
          transform: translateY(0) scale(1);
          box-shadow: 0 6px 20px ${themeColor}40;
        }
        50% {
          transform: translateY(-7px) scale(1.05);
          box-shadow: 0 12px 28px ${themeColor}60;
        }
      }
      .grag-icon-btn.dragging {
        animation: none !important;
        transition: none !important;
        transform: none !important;
      }
      .grag-search-glow button {
        width: 34px;
        height: 34px;
      }
      @media (max-width: 640px) {
        .grag-search-glow button {
          width: 30px !important;
          height: 30px !important;
        }
      }
      .grag-search-wrapper input::placeholder {
        color: #71717a !important;
        font-size: 14px !important;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
        opacity: 1 !important;
      }
    `;
    document.head.appendChild(styleEl);

    // Declare iframe reference (to be lazily loaded)
    let iframe = null;

    // Declared launcher button reference
    let button = null;

    // Declared search wrapper reference
    let searchWrapper = null;
    let searchInput = null;
    let searchGlowContainer = null;
    let searchSendBtn = null;
    let searchPoweredByContainer = null;

    // Draggable utility for the launcher elements
    const clampPosition = (el) => {
      if (!el || !el.style.left) return;
      const left = parseFloat(el.style.left);
      const top = parseFloat(el.style.top);
      const maxLeft = window.innerWidth - el.offsetWidth;
      const maxTop = window.innerHeight - el.offsetHeight;
      el.style.left = Math.max(0, Math.min(maxLeft, left)) + "px";
      el.style.top = Math.max(0, Math.min(maxTop, top)) + "px";
    };

    const makeDraggable = (el, onClickHandler) => {
      let startMouseX = 0, startMouseY = 0;
      let startElLeft = 0, startElTop = 0;
      let isDragging = false;
      let hasMoved = false;

      el.style.cursor = "grab";

      if (onClickHandler) {
        el.addEventListener("click", (e) => {
          if (hasMoved) {
            hasMoved = false;
            e.preventDefault();
            e.stopPropagation();
            return;
          }
          onClickHandler(e);
        });
      }

      // Load saved position safely
      const savedPos = localStorage.getItem(`grag_launcher_pos_${chatType}`);
      if (savedPos) {
        try {
          const { left, top } = JSON.parse(savedPos);
          if (left !== null && left !== undefined && !isNaN(left) &&
              top !== null && top !== undefined && !isNaN(top)) {
            el.style.left = left + "px";
            el.style.top = top + "px";
            el.style.right = "auto";
            el.style.bottom = "auto";
            el.style.transform = "none";
            // Check bounds in case window size changed since last visit
            setTimeout(() => clampPosition(el), 100);
          }
        } catch (e) {}
      }

      const onMouseDown = (e) => {
        if (e.type === "mousedown" && e.button !== 0) return;

        // Ignore interactive child elements to allow standard text selection/clicking
        if (e.target.closest("input") || e.target.closest("a") || (chatType === "search" && e.target.closest("button"))) {
          return;
        }

        const clientX = e.type === "touchstart" ? e.touches[0].clientX : e.clientX;
        const clientY = e.type === "touchstart" ? e.touches[0].clientY : e.clientY;

        const rect = el.getBoundingClientRect();
        startMouseX = clientX;
        startMouseY = clientY;
        startElLeft = rect.left;
        startElTop = rect.top;

        isDragging = false;
        hasMoved = false;

        document.addEventListener("mousemove", onMouseMove, { passive: false });
        document.addEventListener("mouseup", onMouseUp);
        document.addEventListener("touchmove", onMouseMove, { passive: false });
        document.addEventListener("touchend", onMouseUp);
      };

      const onMouseMove = (e) => {
        const clientX = e.type === "touchmove" ? e.touches[0].clientX : e.clientX;
        const clientY = e.type === "touchmove" ? e.touches[0].clientY : e.clientY;

        const dx = clientX - startMouseX;
        const dy = clientY - startMouseY;

        // Check if movement exceeds threshold
        if (!isDragging && (Math.abs(dx) > 5 || Math.abs(dy) > 5)) {
          isDragging = true;
          hasMoved = true;
          el.style.transition = "none";
          el.style.cursor = "grabbing";
          el.classList.add("dragging");
        }

        if (isDragging) {
          if (e.cancelable) e.preventDefault();

          let newLeft = startElLeft + dx;
          let newTop = startElTop + dy;

          const maxLeft = window.innerWidth - el.offsetWidth;
          const maxTop = window.innerHeight - el.offsetHeight;

          newLeft = Math.max(0, Math.min(maxLeft, newLeft));
          newTop = Math.max(0, Math.min(maxTop, newTop));

          el.style.left = newLeft + "px";
          el.style.top = newTop + "px";
          el.style.right = "auto";
          el.style.bottom = "auto";
          el.style.transform = "none";

          if (iframe && iframe.classList.contains("show")) {
            updateIframeDimensions();
          }
        }
      };

      const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.removeEventListener("touchmove", onMouseMove);
        document.removeEventListener("touchend", onMouseUp);

        if (isDragging) {
          isDragging = false;
          el.style.transition = "";
          el.style.cursor = "grab";
          el.classList.remove("dragging");

          const rect = el.getBoundingClientRect();
          localStorage.setItem(`grag_launcher_pos_${chatType}`, JSON.stringify({ left: rect.left, top: rect.top }));
        }
      };

      el.addEventListener("mousedown", onMouseDown);
      el.addEventListener("touchstart", onMouseDown, { passive: true });
    };

    // Global window resize and responsive dimensions
    const updateIframeDimensions = () => {
      if (!iframe) return;
      const isMobile = window.innerWidth <= 640;

      if (chatType === "search") {
        if (isMobile) {
          iframe.style.width = "calc(100% - 32px)";
          iframe.style.top = "auto";
          iframe.style.right = "16px";
          iframe.style.left = "16px";
          iframe.style.borderRadius = "24px";
          iframe.style.transformOrigin = "center bottom";
          iframe.style.transform = "none";
          iframe.style.bottom = "88px";
          iframe.style.height = "380px";
        } else {
          iframe.style.top = "auto";
          iframe.style.borderRadius = "24px";
          if (position === "center") {
            iframe.style.transformOrigin = "center bottom";
          } else {
            iframe.style.transformOrigin = position === "left" ? "left bottom" : "right bottom";
          }

          const safeHeight = Math.min(410, window.innerHeight - 124);
          iframe.style.width = position === "center" ? "680px" : "420px";
          iframe.style.height = safeHeight + "px";
          iframe.style.bottom = "96px";
          if (position === "center") {
            iframe.style.left = "50%";
            iframe.style.right = "auto";
            iframe.style.transform = "translateX(-50%)";
          } else {
            iframe.style.right = "40px";
            iframe.style.left = "auto";
            iframe.style.transform = "none";
          }
        }
      } else {
        // Icon mode - uses draggable rect-based dynamic positioning
        if (!button) return;
        const launcherRect = button.getBoundingClientRect();
        
        // Define dimensions based on device
        let iframeWidth = 420;
        let iframeHeight = Math.min(520, window.innerHeight - 115);
        if (isMobile) {
          iframeWidth = Math.min(window.innerWidth - 32, 380);
          iframeHeight = Math.min(window.innerHeight - 140, 480);
        }

        iframe.style.width = iframeWidth + "px";
        iframe.style.height = iframeHeight + "px";
        iframe.style.borderRadius = "24px";
        iframe.style.transform = "none";

        const spaceAbove = launcherRect.top - 12;
        const spaceBelow = window.innerHeight - launcherRect.bottom - 12;
        const spaceLeft = launcherRect.left - 12;
        const spaceRight = window.innerWidth - launcherRect.right - 12;

        // Determine if we can place the chat window on the side of the button
        // Side placement is possible if the screen is wide enough to fit the iframe on at least one side
        const canPlaceRight = spaceRight >= iframeWidth + 12;
        const canPlaceLeft = spaceLeft >= iframeWidth + 12;
        
        // We prefer side placement if the button is vertically in the middle area,
        // or if the chat window cannot fit vertically above or below the button without overlapping.
        const fitsAbove = spaceAbove >= iframeHeight;
        const fitsBelow = spaceBelow >= iframeHeight;
        const isVerticallyInCenter = spaceAbove >= 180 && spaceBelow >= 180;
        const preferSide = (!fitsAbove && !fitsBelow) || isVerticallyInCenter;
        const useSidePlacement = preferSide && (canPlaceLeft || canPlaceRight);

        let iframeLeft = 0;
        let iframeTop = 0;
        let transformOrigin = "center bottom";

        if (useSidePlacement) {
          // Determine side: Left or Right
          const buttonCenterX = launcherRect.left + launcherRect.width / 2;
          const preferRight = buttonCenterX < window.innerWidth / 2;

          if (preferRight && canPlaceRight) {
            iframeLeft = launcherRect.right + 12;
            transformOrigin = "left center";
          } else if (canPlaceLeft) {
            iframeLeft = launcherRect.left - iframeWidth - 12;
            transformOrigin = "right center";
          } else if (canPlaceRight) {
            iframeLeft = launcherRect.right + 12;
            transformOrigin = "left center";
          }

          // Align vertical center of iframe with button center, clamped to screen
          const buttonCenterY = launcherRect.top + launcherRect.height / 2;
          iframeTop = buttonCenterY - iframeHeight / 2;
          iframeTop = Math.max(10, Math.min(window.innerHeight - iframeHeight - 10, iframeTop));
        } else {
          // Vertical above/below positioning (either because button is near top/bottom boundaries or screen is too narrow for side placement)
          
          // Determine above/below based on which side has more space or button position relative to screen center
          const buttonCenterY = launcherRect.top + launcherRect.height / 2;
          const useAbove = buttonCenterY > window.innerHeight / 2;

          if (useAbove) {
            // Place above the button
            iframeTop = launcherRect.top - iframeHeight - 12;
            transformOrigin = "center bottom";
            // Clamp top to screen boundary
            iframeTop = Math.max(10, iframeTop);
          } else {
            // Place below the button
            iframeTop = launcherRect.bottom + 12;
            transformOrigin = "center top";
            // Clamp bottom to screen boundary
            iframeTop = Math.min(window.innerHeight - iframeHeight - 10, iframeTop);
          }

          // Center horizontally with button, clamped to screen width
          if (isMobile) {
            // Center in screen on mobile
            iframeLeft = (window.innerWidth - iframeWidth) / 2;
          } else {
            // Center relative to button on desktop, clamped
            const buttonCenterX = launcherRect.left + launcherRect.width / 2;
            iframeLeft = buttonCenterX - iframeWidth / 2;
            iframeLeft = Math.max(16, Math.min(window.innerWidth - iframeWidth - 16, iframeLeft));
          }
        }

        iframe.style.left = iframeLeft + "px";
        iframe.style.right = "auto";
        iframe.style.bottom = "auto";
        iframe.style.top = iframeTop + "px";
        iframe.style.transformOrigin = transformOrigin;
      }
    };

    const updateSearchWrapperDimensions = () => {
      if (!searchWrapper) return;
      searchWrapper.classList.remove("layout-center", "layout-right");

      if (searchPoweredByContainer) {
        searchPoweredByContainer.style.position = "fixed";
        searchPoweredByContainer.style.zIndex = "999998";
        searchPoweredByContainer.style.left = "auto";
        searchPoweredByContainer.style.right = "auto";
        searchPoweredByContainer.style.transform = "none";
      }

      const isMobile = window.innerWidth <= 640;
      if (isMobile) {
        searchWrapper.classList.add("layout-center");
        if (searchPoweredByContainer) {
          searchPoweredByContainer.style.bottom = "6px";
          searchPoweredByContainer.style.left = "50%";
          searchPoweredByContainer.style.transform = "translateX(-50%)";
        }
      } else {
        if (position === "center") {
          searchWrapper.classList.add("layout-center");
          if (searchPoweredByContainer) {
            searchPoweredByContainer.style.bottom = "8px";
            searchPoweredByContainer.style.left = "50%";
            searchPoweredByContainer.style.transform = "translateX(-50%)";
          }
        } else {
          searchWrapper.classList.add("layout-right");
          if (searchPoweredByContainer) {
            searchPoweredByContainer.style.bottom = "8px";
            searchPoweredByContainer.style.right = "190px"; // Centered under right search bar
          }
        }
      }
    };

    window.addEventListener("resize", () => {
      if (chatType === "icon" && button) {
        clampPosition(button);
      }
      updateIframeDimensions();
      updateSearchWrapperDimensions();
    });

    // Lazy initialization of the iframe
    const initIframe = () => {
      if (iframe) return iframe;

      // Create Iframe element
      iframe = document.createElement("iframe");
      iframe.className = "grag-iframe-container";
      if (chatType === "search") {
        iframe.classList.add("search-mode");
        if (position === "center") {
          iframe.classList.add("center-search");
        }
      }
      iframe.style.border = "none";
      iframe.style.background = "transparent";
      iframe.style.borderRadius = "24px";
      iframe.style.zIndex = "2147483647";
      iframe.setAttribute("allowtransparency", "true");
      iframe.setAttribute("allow", "clipboard-write");
      iframe.loading = "lazy";
      iframe.src = `${baseUrl}/widget?agentId=${agentId}&tenantId=${tenantId}&chatType=${chatType}&themeColor=${encodeURIComponent(themeColor)}&headerLogo=${encodeURIComponent(resolvedHeaderLogo)}&headerAlign=${encodeURIComponent(headerAlign)}&headerName=${encodeURIComponent(headerName)}&headerSubtext=${encodeURIComponent(headerSubtext)}&agentLabel=${encodeURIComponent(agentLabel)}&themeTextColor=${encodeURIComponent(themeTextColor)}&botAvatar=${encodeURIComponent(resolvedBotAvatar)}&buttonIcon=${encodeURIComponent(resolvedButtonIcon)}&buttonAlign=${encodeURIComponent(buttonAlign)}&showButtonText=${showButtonText}&buttonText=${encodeURIComponent(buttonText)}&initialMessage=${encodeURIComponent(initialMessage)}&displaySources=${displaySources}&allowDownloads=${allowDownloads}&displayCopy=${displayCopy}&displayFeedback=${displayFeedback}&linkSafety=${linkSafety}&leadCollection=${leadCollection}&leadFields=${encodeURIComponent(leadFields)}&leadTiming=${leadTiming}&escalationEnabled=${escalationEnabled}&escalationLink=${encodeURIComponent(escalationLink)}&placeholder=${encodeURIComponent(placeholder)}`;

      iframe.addEventListener("load", () => {
        iframe.setAttribute("data-loaded", "true");
      });

      // Set dimensions and append to body
      updateIframeDimensions();
      document.body.appendChild(iframe);
      return iframe;
    };

    let isClosingFromPopstate = false;

    const openIframe = (initialQuery = "") => {
      const currentIframe = initIframe();
      
      updateIframeDimensions();

      if (chatType === "search" && searchPoweredByContainer) {
        searchPoweredByContainer.style.display = "flex";
      }

      if (currentIframe.getAttribute("data-loaded") === "true") {
        currentIframe.classList.add("show");
        currentIframe.contentWindow.postMessage({ type: "focus-input" }, "*");
      } else {
        currentIframe.addEventListener("load", () => {
          currentIframe.classList.add("show");
          currentIframe.contentWindow.postMessage({ type: "focus-input" }, "*");
        }, { once: true });
      }

      // Push state to browser history so back button closes it on mobile
      if (window.innerWidth <= 640) {
        if (window.history.state?.gragWidgetOpen !== true) {
          window.history.pushState({ gragWidgetOpen: true }, "");
        }
      }

      // Send initial query via postMessage to avoid slow reloads
      if (initialQuery) {
        setTimeout(() => {
          currentIframe.contentWindow.postMessage({ type: "send-query", query: initialQuery }, "*");
        }, 50);
      }
    };

    const closeIframe = () => {
      if (iframe) {
        if (chatType === "search") {
          // Trigger close animation inside search widget first
          iframe.contentWindow.postMessage({ type: "start-close-animation" }, "*");
        } else {
          iframe.classList.remove("show");
          // Clean up browser history state if we pushed it and are NOT closing from popstate
          if (window.innerWidth <= 640 && !isClosingFromPopstate && window.history.state?.gragWidgetOpen === true) {
            window.history.back();
          }
        }
      }
    };

    // Listen to browser back button popstate
    window.addEventListener("popstate", (event) => {
      if (iframe && iframe.classList.contains("show")) {
        isClosingFromPopstate = true;
        closeIframe();
        isClosingFromPopstate = false;
      }
    });

    // Listen to postMessage from the iframe widget to close/collapse the chat window
    window.addEventListener("message", (event) => {
      if (event.data && (event.data.type === "close-chat" || event.data.type === "close")) {
        if (iframe) {
          iframe.classList.remove("show");
        }
        if (window.innerWidth <= 640 && !isClosingFromPopstate && window.history.state?.gragWidgetOpen === true) {
          window.history.back();
        }
        // Reset the parent search bar input state when closed
        if (chatType === "search" && searchInput) {
          searchInput.value = "";
          searchInput.blur();
          if (searchGlowContainer) {
            searchGlowContainer.classList.remove("active");
          }
          if (searchSendBtn) {
            searchSendBtn.style.background = "#f4f4f5";
            searchSendBtn.style.color = "#a1a1aa";
            searchSendBtn.disabled = true;
          }
          if (searchPoweredByContainer) {
            searchPoweredByContainer.style.display = "none";
          }
        }
      }
      // Typing state sync from iframe to parent search bar
      if (event.data && event.data.type === "set-typing") {
        const isBotTyping = event.data.isTyping;
        if (searchInput) {
          const wasDisabled = searchInput.disabled;
          searchInput.disabled = isBotTyping;
          searchInput.style.cursor = isBotTyping ? "not-allowed" : "text";
          searchInput.placeholder = placeholder;
          if (!isBotTyping) {
            setTimeout(() => {
              searchInput.focus();
            }, 100);
          }
        }
        if (searchSendBtn) {
          searchSendBtn.disabled = isBotTyping;
          if (isBotTyping) {
            searchSendBtn.style.background = "#f4f4f5";
            searchSendBtn.style.color = "#a1a1aa";
          } else {
            if (searchInput && searchInput.value.trim().length > 0) {
              searchSendBtn.style.background = themeColor;
              searchSendBtn.style.color = "#ffffff";
              searchSendBtn.disabled = false;
            }
          }
        }
      }
    });

    if (chatType === "search") {
      // --- Style 2: Search Bar Style Chat ---
      searchWrapper = document.createElement("div");
      searchWrapper.className = "grag-search-wrapper";

      updateSearchWrapperDimensions();

      // Outer glow container (which handles brand gradient outline on focus/hover)
      searchGlowContainer = document.createElement("div");
      searchGlowContainer.className = "grag-search-glow";

      // Inner input bar container
      const inputBar = document.createElement("div");
      inputBar.style.display = "flex";
      inputBar.style.alignItems = "center";
      inputBar.style.background = "#ffffff";
      inputBar.style.borderRadius = "24px";
      inputBar.style.padding = "6px 8px 6px 18px";
      inputBar.style.gap = "12px";
      inputBar.style.boxSizing = "border-box";
      inputBar.style.height = "46px";

      // Left Icon (Clock/History SVG)
      const leftIcon = document.createElement("span");
      leftIcon.style.display = "flex";
      leftIcon.style.alignItems = "center";
      leftIcon.style.color = "#71717a";
      leftIcon.style.cursor = "pointer";
      leftIcon.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
      `;

      // Input Element
      searchInput = document.createElement("input");
      searchInput.type = "text";
      searchInput.placeholder = placeholder;
      searchInput.style.flex = "1";
      searchInput.style.border = "none";
      searchInput.style.outline = "none";
      searchInput.style.background = "transparent";
      searchInput.style.color = "#18181b";
      searchInput.style.fontSize = "14px";
      searchInput.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
      searchInput.style.padding = "0";
      searchInput.style.height = "20px";
      searchInput.style.lineHeight = "20px";

      // Right Send Button
      searchSendBtn = document.createElement("button");
      searchSendBtn.style.width = "34px";
      searchSendBtn.style.height = "34px";
      searchSendBtn.style.borderRadius = "50%";
      searchSendBtn.style.background = "#f4f4f5"; // grey default
      searchSendBtn.style.border = "none";
      searchSendBtn.style.cursor = "pointer";
      searchSendBtn.style.display = "flex";
      searchSendBtn.style.alignItems = "center";
      searchSendBtn.style.justifyContent = "center";
      searchSendBtn.style.transition = "background-color 0.2s ease, transform 0.2s ease";
      searchSendBtn.style.color = "#a1a1aa";
      searchSendBtn.disabled = true;
      searchSendBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="19" x2="12" y2="5"/>
          <polyline points="5 12 12 5 19 12"/>
        </svg>
      `;

      searchInput.onfocus = () => {
        if (!userInteracted) return;
        searchGlowContainer.classList.add("active");
        openIframe("");
      };
      searchInput.onclick = () => {
        userInteracted = true;
        searchGlowContainer.classList.add("active");
        openIframe("");
      };
      searchInput.onmouseenter = () => {
        initIframe();
      };
      searchInput.onblur = () => {
        if (searchInput.value.trim() === "") {
          searchGlowContainer.classList.remove("active");
        }
      };
      searchInput.oninput = (e) => {
        const val = e.target.value.trim();
        if (val.length > 0) {
          searchGlowContainer.classList.add("active");
          searchSendBtn.style.background = themeColor;
          searchSendBtn.style.color = "#ffffff";
          searchSendBtn.disabled = false;
        } else {
          searchGlowContainer.classList.remove("active");
          searchSendBtn.style.background = "#f4f4f5";
          searchSendBtn.style.color = "#a1a1aa";
          searchSendBtn.disabled = true;
        }
      };

      const handleSearchSubmit = () => {
        const query = searchInput.value.trim();
        if (!query) return;
        openIframe(query);
        searchInput.value = "";
        searchSendBtn.style.background = "#f4f4f5";
        searchSendBtn.style.color = "#a1a1aa";
        searchSendBtn.disabled = true;
        searchGlowContainer.classList.remove("active");
      };

      searchInput.onkeydown = (e) => {
        if (e.key === "Enter") {
          handleSearchSubmit();
        }
      };

      searchSendBtn.onclick = () => {
        handleSearchSubmit();
      };
      leftIcon.onclick = () => {
        openIframe("");
      };

      // Powered by Gramosoft label wrapper
      searchPoweredByContainer = document.createElement("div");
      searchPoweredByContainer.style.display = "none"; // Hidden by default when search bar is closed
      searchPoweredByContainer.style.justifyContent = "center";
      searchPoweredByContainer.style.marginTop = "6px";
   
      const poweredBy = document.createElement("a");
      poweredBy.href = "https://gsearchai.com/";
      poweredBy.target = "_blank";
      poweredBy.rel = "noopener noreferrer";
      poweredBy.style.display = "inline-flex";
      poweredBy.style.alignItems = "center";
      poweredBy.style.justifyContent = "center";
      poweredBy.style.gap = "4px";
      poweredBy.style.padding = "4px 12px";
      poweredBy.style.fontSize = "11px";
      poweredBy.style.color = "#18181b";
      poweredBy.style.fontWeight = "600";
      poweredBy.style.userSelect = "none";
      poweredBy.style.textDecoration = "none";
      poweredBy.style.cursor = "pointer";
      poweredBy.style.borderRadius = "100px";
      poweredBy.style.background = "#ffffff";
      poweredBy.style.border = "1px solid #d4d4d8";
      poweredBy.style.boxShadow = "0 2px 6px rgba(0, 0, 0, 0.08)";
      poweredBy.style.transition = "all 0.2s ease-in-out";
      poweredBy.innerHTML = `Powered by <span style="font-weight: 750; color: ${themeColor};">Gsearch</span>`;
   
      poweredBy.addEventListener("mouseenter", () => {
        poweredBy.style.transform = "translateY(-1px)";
        poweredBy.style.boxShadow = "0 4px 12px rgba(0, 0, 0, 0.12)";
      });
      poweredBy.addEventListener("mouseleave", () => {
        poweredBy.style.transform = "none";
        poweredBy.style.boxShadow = "0 2px 6px rgba(0, 0, 0, 0.08)";
      });
   
      searchPoweredByContainer.appendChild(poweredBy);
   
      // Assemble and render elements
      inputBar.appendChild(leftIcon);
      inputBar.appendChild(searchInput);
      inputBar.appendChild(searchSendBtn);
      searchGlowContainer.appendChild(inputBar);
      searchWrapper.appendChild(searchGlowContainer);
      document.body.appendChild(searchWrapper);
      document.body.appendChild(searchPoweredByContainer);
      
      // Position searchWrapper correctly on load
      updateSearchWrapperDimensions();
    } else {
      // --- Style 1: Classic Icon Style Chat ---
      button = document.createElement("button");
      button.className = "grag-icon-btn";
      if (showButtonText && buttonText) {
        button.style.width = "auto";
        button.style.borderRadius = "30px";
        button.style.padding = "0 18px";
        button.style.gap = "8px";
      }

      let iconHtml = "";
      if (resolvedButtonIcon && (resolvedButtonIcon.startsWith("http") || resolvedButtonIcon.startsWith("blob:") || resolvedButtonIcon.startsWith("data:"))) {
        iconHtml = `<img src="${resolvedButtonIcon}" style="width: 28px; height: 28px; border-radius: 50%; object-fit: contain;" />`;
      } else if (resolvedButtonIcon === "robot") {
        iconHtml = `<div style="width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="${themeTextColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2" fill="none"/><circle cx="8.5" cy="15.5" r="1.5" fill="${themeTextColor}"/><circle cx="15.5" cy="15.5" r="1.5" fill="${themeTextColor}"/><path d="M12 2v6M9 5h6"/></svg></div>`;
      } else if (resolvedButtonIcon === "setting") {
        iconHtml = `<div style="width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="${themeTextColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.1a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3" fill="none"/></svg></div>`;
      } else if (resolvedButtonIcon === "question") {
        iconHtml = `<div style="width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="${themeTextColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div>`;
      } else if (resolvedButtonIcon === "book") {
        iconHtml = `<div style="width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="${themeTextColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></div>`;
      } else {
        iconHtml = `
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M21 11.5C21 16.7467 16.9706 21 12 21C10.1302 21 8.39632 20.3992 6.97743 19.3722L3 20.5L4.15064 16.6329C3.41732 15.1543 3 13.4754 3 11.5C3 6.25329 7.02944 2 12 2C16.9706 2 21 6.25329 21 11.5Z" fill="${themeTextColor}" stroke="${themeTextColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="8" cy="11.5" r="1.3" fill="${btnBgColor}"/>
            <circle cx="12" cy="11.5" r="1.3" fill="${btnBgColor}"/>
            <circle cx="16" cy="11.5" r="1.3" fill="${btnBgColor}"/>
          </svg>
        `;
      }

      button.innerHTML = iconHtml + (showButtonText && buttonText ? `<span style="font-weight: 700; font-size: 14px; color: ${themeTextColor}; font-family: sans-serif;">${buttonText}</span>` : "");

      document.body.appendChild(button);

      // Fetch Customization API if tenantId exists to apply logo_url to embed launch button if show_in_embed is true
      if (tenantId) {
        try {
          const custApiUrl = `${baseUrl.endsWith("/api/v1") ? baseUrl : baseUrl + "/api/v1"}/embed/customization?tenant_id=${tenantId}`;
          fetch(custApiUrl)
            .then(res => res.json())
            .then(result => {
              const data = result.data || result;
              if (data && data.logo_url && data.show_in_embed && button && (buttonIcon === "chat" || !buttonIcon)) {
                const proxyLogo = toProxyUrl(data.logo_url);
                const imgHtml = `<img src="${proxyLogo}" style="width: 28px; height: 28px; border-radius: 50%; object-fit: contain;" />`;
                button.innerHTML = imgHtml + (showButtonText && buttonText ? `<span style="font-weight: 700; font-size: 14px; color: ${themeTextColor}; font-family: sans-serif;">${buttonText}</span>` : "");
              }
            })
            .catch(e => console.warn("GragWidget: Customization fetch error", e));
        } catch (e) { }
      }

      // Make it draggable with toggle click trigger
      makeDraggable(button, () => {
        if (iframe && iframe.classList.contains("show")) {
          closeIframe();
        } else {
          openIframe();
        }
      });
      button.onmouseenter = () => {
        initIframe();
      };
    }

    // Pre-load the iframe widget in the background so it responds instantly
    if (document.readyState === "complete" || document.readyState === "interactive") {
      initIframe();
    } else {
      window.addEventListener("DOMContentLoaded", () => initIframe());
    }
  }
})();