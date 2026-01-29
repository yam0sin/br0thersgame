const POOL_SIZE = 40;
const SPIN_TILES = 90;
const SPIN_DURATION_MS = 10000;
const MIN_TILES = 120;
const EXTRA_BUFFER = 20;

let isSpinning = false;

function qs(selector) {
  return document.querySelector(selector);
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function createRouletteItem(skin) {
  const item = document.createElement("div");
  item.className = "roulette-item";
  const rarity = (skin.rarity || "").toLowerCase().replace(/\d+$/g, "").trim();
  if (rarity.includes("ширпотреб")) {
    item.classList.add("rarity-consumer");
  } else if (rarity.includes("промышлен")) {
    item.classList.add("rarity-industrial");
  } else if (rarity.includes("армей")) {
    item.classList.add("rarity-milspec");
  } else if (rarity.includes("запрещ")) {
    item.classList.add("rarity-restricted");
  } else if (rarity.includes("засекр")) {
    item.classList.add("rarity-classified");
  } else if (rarity.includes("тайн")) {
    item.classList.add("rarity-covert");
  }
  const quality = (skin.quality || "").toLowerCase();
  if (quality.includes("прямо")) {
    item.classList.add("q-fn");
  } else if (quality.includes("немного")) {
    item.classList.add("q-mw");
  } else if (quality.includes("полев")) {
    item.classList.add("q-ft");
  } else if (quality.includes("понош")) {
    item.classList.add("q-ws");
  } else if (quality.includes("закал")) {
    item.classList.add("q-bs");
  }
  const img = document.createElement("img");
  img.loading = "lazy";
  img.decoding = "async";
  img.src = skin.image_url;
  img.alt = skin.name;
  const name = document.createElement("div");
  name.className = "skin-name";
  name.textContent = skin.name;
  const price = document.createElement("div");
  price.className = "skin-price";
  price.textContent = `${skin.price}★`;
  item.appendChild(img);
  item.appendChild(name);
  item.appendChild(price);
  return item;
}

function updateBalance(newBalance) {
  const balanceEl = qs(".user-balance");
  if (balanceEl) {
    balanceEl.textContent = `Баланс: ${newBalance}★`;
  }
}

function showModal(drop, inventoryItemId) {
  const modal = qs("#drop-modal");
  const modalBody = qs("#modal-body");
  if (!modal || !modalBody) return;
  modalBody.querySelector(".modal-image").innerHTML = `<img src="${drop.image_url}" alt="${drop.name}" />`;
  modalBody.querySelector(".modal-name").textContent = drop.name;
  modalBody.querySelector(".modal-quality").textContent = drop.quality;
  modalBody.querySelector(".modal-price").textContent = `${drop.price}★`;
  modal.classList.add("active");

  const sellBtn = qs("#sell-btn");
  const keepBtn = qs("#keep-btn");
  if (sellBtn) {
    sellBtn.onclick = async () => {
      await fetch(window.SellUrlBase.replace("/0", `/${inventoryItemId}`), {
        method: "POST",
      });
      window.location.reload();
    };
  }
  if (keepBtn) {
    keepBtn.onclick = hideModal;
  }
}

function hideModal() {
  const modal = qs("#drop-modal");
  if (modal) modal.classList.remove("active");
}

function getRouletteMetrics(track, wrap) {
  const trackStyles = getComputedStyle(track);
  const rawWidth = trackStyles.getPropertyValue("--roulette-item-width");
  const itemWidth = Number.parseFloat(rawWidth) || 170;
  const gap = Number.parseFloat(trackStyles.columnGap || trackStyles.gap) || 14;
  const containerWidth = wrap.clientWidth || 0;
  return {
    itemWidth,
    gap,
    fullWidth: itemWidth + gap,
    containerWidth,
  };
}

function runRoulette(resultSkin, onFinish) {
  const track = qs("#roulette-track");
  const wrap = qs("#roulette-wrap");
  if (!track || !wrap) {
    if (onFinish) onFinish();
    return;
  }

  const all = window.SkinsData || [];
  if (!all.length) {
    if (onFinish) onFinish();
    return;
  }

  const { itemWidth, fullWidth, containerWidth } = getRouletteMetrics(track, wrap);
  const buffer = Math.ceil(containerWidth / fullWidth) * 2 + EXTRA_BUFFER;
  const pool = [];
  const poolSource = [...all];
  while (pool.length < POOL_SIZE && poolSource.length) {
    const idx = Math.floor(Math.random() * poolSource.length);
    pool.push(poolSource.splice(idx, 1)[0]);
  }
  if (!pool.length) {
    if (onFinish) onFinish();
    return;
  }
  const randomIndex = Math.floor(Math.random() * pool.length);
  const winIndex = buffer + SPIN_TILES + randomIndex;
  const totalTiles = Math.max(MIN_TILES, winIndex + buffer + 1);

  const tiles = new Array(totalTiles);
  for (let i = 0; i < totalTiles; i += 1) {
    tiles[i] = pool[Math.floor(Math.random() * pool.length)];
  }
  tiles[winIndex] = resultSkin;

  const preloadFirstImages = (list, limit = 20) => {
    list.slice(0, limit).forEach((skin) => {
      const img = new Image();
      img.decoding = "async";
      img.src = skin.image_url;
    });
  };

  track.innerHTML = "";
  track.style.transition = "none";
  track.style.transform = "translateX(0px)";
  track.offsetWidth;

  preloadFirstImages(tiles, 20);

  const fragment = document.createDocumentFragment();
  tiles.forEach((skin) => {
    fragment.appendChild(createRouletteItem(skin));
  });
  track.appendChild(fragment);

  const centerOffset = containerWidth / 2 - itemWidth / 2;
  const startTranslate = -(buffer * fullWidth) + centerOffset;
  const targetTranslate = -(winIndex * fullWidth) + centerOffset;
  const durationMs = SPIN_DURATION_MS;

  track.style.transition = "none";
  track.style.transform = `translateX(${startTranslate}px)`;
  track.offsetWidth;

  const onTransitionEnd = (event) => {
    if (event.propertyName !== "transform") return;
    track.removeEventListener("transitionend", onTransitionEnd);
    if (onFinish) onFinish();
  };
  track.addEventListener("transitionend", onTransitionEnd);

  requestAnimationFrame(() => {
    track.style.transition = `transform ${durationMs}ms cubic-bezier(0.12, 0.85, 0.15, 1)`;
    track.style.transform = `translateX(${targetTranslate}px)`;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const openCaseBtn = qs("#open-case-btn");
  const closeBtn = qs("#modal-close");
  const modal = qs("#drop-modal");

  if (openCaseBtn) {
    openCaseBtn.addEventListener("click", async () => {
      if (isSpinning) return;
      isSpinning = true;
      openCaseBtn.disabled = true;
      try {
        const response = await fetch(window.OpenCaseUrl, { method: "POST" });
        const data = await response.json();
        if (!response.ok) {
          alert(data.error || "Ошибка открытия кейса.");
          isSpinning = false;
          openCaseBtn.disabled = false;
          return;
        }
        runRoulette(data.skin, () => {
          showModal(data.skin, data.inventory_item_id);
          isSpinning = false;
          openCaseBtn.disabled = false;
        });
        updateBalance(data.balance);
      } catch (err) {
        alert("Ошибка сети.");
        isSpinning = false;
        openCaseBtn.disabled = false;
      }
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", hideModal);
  }

  if (modal) {
    modal.addEventListener("click", (event) => {
      if (event.target === modal) hideModal();
    });
  }

  const chatForm = qs("#chat-form");
  const chatWindow = qs("#chat-window");
  let lastChatId = 0;
  if (chatWindow) {
    const items = Array.from(chatWindow.querySelectorAll(".chat-item"));
    if (items.length) {
      lastChatId = Math.max(
        ...items.map((item) => Number(item.dataset.id || 0)),
      );
    }
  }

  const trimChat = () => {
    if (!chatWindow) return;
    let items = chatWindow.querySelectorAll(".chat-item");
    while (items.length > 20) {
      const last = items[items.length - 1];
      if (last) last.remove();
      items = chatWindow.querySelectorAll(".chat-item");
    }
  };

  const removeEmpty = () => {
    if (!chatWindow) return;
    const empty = chatWindow.querySelector(".empty");
    if (empty) empty.remove();
  };

  if (chatForm) {
    chatForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = chatForm.querySelector("input[name='message']");
      if (!input || !input.value.trim()) return;
      const formData = new FormData();
      formData.append("message", input.value.trim());
      const response = await fetch(window.ChatSendUrl, {
        method: "POST",
        body: formData,
      });
      if (response.ok) {
        const data = await response.json();
        const item = document.createElement("div");
        item.className = "chat-item";
        item.dataset.id = data.id;
        item.innerHTML = `<span class="chat-user">@${data.username}</span><span class="chat-text">${data.message}</span>`;
        removeEmpty();
        chatWindow.prepend(item);
        chatWindow.scrollTop = 0;
        input.value = "";
        lastChatId = Math.max(lastChatId, data.id);
        trimChat();
      }
    });
  }

  if (chatWindow) {
    setInterval(async () => {
      const response = await fetch(`${window.ChatPollUrl}?since_id=${lastChatId}`);
      if (!response.ok) return;
      const data = await response.json();
      if (!Array.isArray(data) || data.length === 0) return;
      data.forEach((msg) => {
        const item = document.createElement("div");
        item.className = "chat-item";
        item.dataset.id = msg.id;
        item.innerHTML = `<span class="chat-user">@${msg.username}</span><span class="chat-text">${msg.message}</span>`;
        removeEmpty();
        chatWindow.prepend(item);
        lastChatId = Math.max(lastChatId, msg.id);
      });
      chatWindow.scrollTop = 0;
      trimChat();
    }, 5000);
  }

  const upgradeItems = qs("#upgrade-items");
  const pickBtn = qs("#upgrade-pick");
  const attemptBtn = qs("#upgrade-attempt");
  const targetName = qs("#target-name");
  const targetQuality = qs("#target-quality");
  const targetPrice = qs("#target-price");
  const targetChance = qs("#target-chance");
  const targetImage = qs("#target-image");
  const targetPanel = qs("#upgrade-target");
  const targetResult = qs("#target-result");
  let currentFromId = null;
  let currentTargetId = null;

  let upgradeBusy = false;

  const setButtonsDisabled = (disabled) => {
    if (pickBtn) pickBtn.disabled = disabled;
    if (attemptBtn) attemptBtn.disabled = disabled;
  };

  const showUpgradeState = (state, message) => {
    if (!targetPanel || !targetResult) return;
    targetPanel.classList.remove("upgrade-processing", "upgrade-success", "upgrade-fail");
    targetResult.textContent = "";
    if (state === "processing") {
      targetPanel.classList.add("upgrade-processing");
      targetResult.textContent = message || "Обработка...";
      return;
    }
    if (state === "success") {
      targetPanel.classList.add("upgrade-success");
      targetResult.textContent = message || "Успех!";
      return;
    }
    if (state === "fail") {
      targetPanel.classList.add("upgrade-fail");
      targetResult.textContent = message || "Неудача";
    }
  };

  const setTargetView = (target, chance) => {
    if (!target) return;
    currentTargetId = target.id;
    if (targetName) targetName.textContent = target.name;
    if (targetQuality) targetQuality.textContent = target.quality;
    if (targetPrice) targetPrice.textContent = `${target.price}★`;
    if (targetChance) targetChance.textContent = `Шанс: ${(chance * 100).toFixed(1)}%`;
    if (targetImage) targetImage.src = target.image_url;
    showUpgradeState(null);
  };

  const pickTarget = async () => {
    if (!currentFromId) {
      showUpgradeState("fail", "Выберите предмет.");
      return;
    }
    const formData = new FormData();
    formData.append("from_item_id", currentFromId);
    const response = await fetch(window.UpgradePickUrl, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      showUpgradeState("fail", data.error || "Не удалось выбрать цель.");
      return;
    }
    setTargetView(data.target_skin, data.chance);
  };

  const attemptUpgrade = async () => {
    if (!currentFromId || !currentTargetId) {
      showUpgradeState("fail", "Выберите предмет и цель.");
      return;
    }
    upgradeBusy = true;
    setButtonsDisabled(true);
    showUpgradeState("processing", "Апгрейд...");
    const formData = new FormData();
    formData.append("from_item_id", currentFromId);
    formData.append("target_skin_id", currentTargetId);
    const response = await fetch(window.UpgradeAttemptUrl, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      showUpgradeState("fail", data.error || "Ошибка апгрейда.");
      upgradeBusy = false;
      setButtonsDisabled(false);
      return;
    }
    if (data.result === "success") {
      showUpgradeState("success", "Успех!");
    } else {
      showUpgradeState("fail", "Неудача");
    }
    setTimeout(() => window.location.reload(), 800);
  };

  if (upgradeItems) {
    upgradeItems.addEventListener("click", (event) => {
      const card = event.target.closest(".upgrade-card");
      if (!card) return;
      upgradeItems.querySelectorAll(".upgrade-card").forEach((el) => {
        el.classList.remove("selected");
      });
      card.classList.add("selected");
      currentFromId = Number(card.dataset.itemId || 0);
      currentTargetId = null;
      pickTarget();
    });
  }

  if (pickBtn) {
    pickBtn.addEventListener("click", pickTarget);
  }
  if (attemptBtn) {
    attemptBtn.addEventListener("click", attemptUpgrade);
  }

  const dropsScroller = qs(".drops-scroller");
  if (dropsScroller) {
    dropsScroller.addEventListener(
      "wheel",
      (event) => {
        if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
        event.preventDefault();
        dropsScroller.scrollBy({ left: event.deltaY, behavior: "auto" });
      },
      { passive: false }
    );
  }

});
