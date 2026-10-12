import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import {
  FileText,
  FileCode,
  Plus,
  ChevronUp,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  ArrowLeft,
  Square,
  X,
  History,
  MoreHorizontal,
  Check,
  Clock,
} from "lucide-react";
import type {
  ChatMessage,
  Citation,
  ErrorReport,
  RepoSummary,
  TranscribeResponse,
  FixTask,
  ConversationItem,
  ApinexQuotaResponse,
} from "../types";
import ErrorSuggestionCard from "./ErrorSuggestionCard";
import {
  streamAsk,
  fetchAiRegistry,
  fetchApinexQuota,
  fetchApiKeyStatus,
  saveApiKeys,
  fetchConversations,
  createConversation,
  fetchConversation,
  addConversationMessage,
  deleteConversation,
} from "../api";
import VoiceMicButton, { speakResponse } from "./VoiceMicButton";
import { parseDiffFiles, type ChangedFileItem } from "../utils/diffParser";
import MarkdownRenderer from "./MarkdownRenderer";

interface Props {
  repo: RepoSummary;
  activeFilePath?: string;
  onFixClick: (citation: Citation) => void;
  activeFixTask?: FixTask | null;
  onApplyFix?: (task: FixTask) => void;
  onRejectFix?: (task: FixTask) => void;
  onReviewDiff?: (task: FixTask, specificPath?: string, specificDiff?: string) => void;
  onClose?: () => void;
}

interface ChatModelOption {
  id: string;
  displayName: string;
  name?: string;
  providerId: string;
  providerDisplayName: string;
  provider?: string;
  providerLabel?: string;
  badge: string;
  capabilities?: string[];
  status?: string;
}

const AUTO_MODEL_OPTION: ChatModelOption = {
  id: "auto",
  displayName: "Auto",
  name: "Auto",
  providerId: "auto",
  providerDisplayName: "Smart Router",
  provider: "auto",
  providerLabel: "Smart Router",
  badge: "AUTO",
  capabilities: ["chat", "code", "reasoning", "vision", "fast"],
  status: "available",
};

const DEFAULT_MODELS: ChatModelOption[] = [
  AUTO_MODEL_OPTION,
  {
    id: "gemini-3.8-flash",
    displayName: "Gemini 3.8 Flash Medium",
    name: "Gemini 3.8 Flash Medium",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    provider: "nvidia",
    providerLabel: "NVIDIA",
    badge: "RECOMMENDED",
    capabilities: ["chat", "code", "reasoning"],
    status: "available",
  },
  {
    id: "glm-5-3",
    displayName: "GLM 5.3",
    name: "GLM 5.3",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    provider: "nvidia",
    providerLabel: "NVIDIA",
    badge: "RECOMMENDED",
    capabilities: ["chat", "code", "reasoning"],
    status: "available",
  },
  {
    id: "glm-5-3-flash",
    displayName: "GLM 5.3 Flash",
    name: "GLM 5.3 Flash",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    provider: "nvidia",
    providerLabel: "NVIDIA",
    badge: "FAST",
    capabilities: ["chat", "fast"],
    status: "available",
  },
  {
    id: "deepseek-v4.1-flash",
    displayName: "DeepSeek V4.1 Flash",
    name: "DeepSeek V4.1 Flash",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    provider: "nvidia",
    providerLabel: "NVIDIA",
    badge: "CODING / REASONING",
    capabilities: ["chat", "code", "reasoning"],
    status: "available",
  },
  {
    id: "llama-3.3-70b-versatile",
    displayName: "Llama 3.3 70B",
    name: "Llama 3.3 70B",
    providerId: "groq",
    providerDisplayName: "Groq",
    provider: "groq",
    providerLabel: "Groq",
    badge: "FALLBACK",
    capabilities: ["chat", "code"],
    status: "available",
  },
  {
    id: "free/gpt-6-luna",
    displayName: "GPT-6 Luna",
    name: "GPT-6 Luna",
    providerId: "apinex",
    providerDisplayName: "APInex",
    provider: "apinex",
    providerLabel: "APInex",
    badge: "DAILY QUOTA: 315K",
    capabilities: ["chat", "code", "reasoning"],
    status: "available",
  },
];

function getWelcomeMessageContent(repoName?: string): string {
  if (repoName && repoName.trim()) {
    return `Hi, I'm CodeBrain AI. How can I help you with **${repoName.trim()}**? Ask me anything, attach an image, or speak using the microphone.`;
  }
  return "Hi, I'm CodeBrain AI. How can I help you today? Ask me anything, attach an image, or speak using the microphone.";
}

interface QueuedMessage {
  id: string;
  query: string;
  image?: File | null;
}

export default function ChatPanel({
  repo,
  activeFilePath,
  onFixClick: _onFixClick,
  activeFixTask,
  onApplyFix,
  onRejectFix,
  onReviewDiff,
  onClose,
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content: getWelcomeMessageContent(repo?.name),
    },
  ]);

  // Dynamically update welcome message when active repository changes
  useEffect(() => {
    setMessages((prev) => {
      if (
        prev.length === 1 &&
        prev[0].role === "assistant" &&
        (prev[0].id.startsWith("welcome") || prev[0].id === "welcome")
      ) {
        return [
          {
            id: `welcome-${repo?.repo_id || "active"}`,
            role: "assistant",
            content: getWelcomeMessageContent(repo?.name),
          },
        ];
      }
      return prev;
    });
  }, [repo?.name, repo?.repo_id]);

  const [input, setInput] = useState("");
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [queuedMessage, setQueuedMessage] = useState<QueuedMessage | null>(null);
  const queuedMessageRef = useRef<QueuedMessage | null>(null);
  queuedMessageRef.current = queuedMessage;

  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const activeRequestIdRef = useRef<number>(0);

  const [voiceHint, setVoiceHint] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<ChatModelOption[]>(DEFAULT_MODELS);
  const [selectedModel, setSelectedModel] = useState<ChatModelOption>(() => {
    const lunaModel = DEFAULT_MODELS.find((m) => m.id === "free/gpt-6-luna") || DEFAULT_MODELS[0];
    try {
      const savedProv = localStorage.getItem("codebrain_selected_ai_provider");
      const savedModel = localStorage.getItem("codebrain_selected_ai_model");
      if (savedProv === "auto" || savedModel === "auto") {
        return AUTO_MODEL_OPTION;
      }
      if (savedProv && savedModel) {
        const found = DEFAULT_MODELS.find(
          (m) => m.providerId === savedProv && m.id === savedModel
        );
        if (found) return found;
      }
    } catch {}
    return lunaModel;
  });
  const [isModelMenuOpen, setIsModelMenuOpen] = useState(false);
  const [isMoreMenuOpen, setIsMoreMenuOpen] = useState(false);
  const [apinexQuota, setApinexQuota] = useState<ApinexQuotaResponse | null>(null);

  const refreshApinexQuota = useCallback(() => {
    fetchApinexQuota()
      .then((q) => {
        if (q) setApinexQuota(q);
      })
      .catch(() => {});
  }, []);

  // Conversation history
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);

  // Canonical changed files review state
  const [isChangedFilesExpanded, setIsChangedFilesExpanded] = useState(false);

  const pendingFiles: ChangedFileItem[] = useMemo(() => {
    if (
      !activeFixTask ||
      !activeFixTask.diff ||
      activeFixTask.stage === "REJECTED" ||
      activeFixTask.stage === "APPLIED"
    ) {
      return [];
    }
    return parseDiffFiles(activeFixTask.diff, activeFixTask.errorReport?.file_path || "");
  }, [activeFixTask]);

  const totalLinesChanged = useMemo(() => {
    return pendingFiles.reduce(
      (acc, f) => ({
        added: acc.added + f.linesAdded,
        deleted: acc.deleted + f.linesDeleted,
      }),
      { added: 0, deleted: 0 }
    );
  }, [pendingFiles]);

  const activeConvTitle = useMemo(() => {
    if (activeConvId) {
      const match = conversations.find((c) => c.id === activeConvId);
      if (match && match.title) return match.title;
    }
    return "CodeBrain AI";
  }, [activeConvId, conversations]);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);
  const speakOnDoneRef = useRef(false);

  const loadConversations = useCallback(async () => {
    try {
      const res = await fetchConversations(repo.repo_id);
      if (res && res.conversations) {
        setConversations(res.conversations);
        if (res.conversations.length > 0) {
          const savedConvId = localStorage.getItem(`codebrain_active_conv_${repo.repo_id}`);
          const candidate = res.conversations.find((c: any) => c.id === savedConvId) || res.conversations[0];
          if (candidate && (!activeConvId || activeConvId !== candidate.id)) {
            setActiveConvId(candidate.id);
            try {
              localStorage.setItem(`codebrain_active_conv_${repo.repo_id}`, candidate.id);
            } catch {}
            try {
              const full = await fetchConversation(repo.repo_id, candidate.id);
              if (full && full.messages && full.messages.length > 0) {
                setMessages(
                  full.messages.map((m: any) => ({
                    id: m.id,
                    role: m.role,
                    content: m.content,
                    errorReports: m.error_reports,
                  }))
                );
              }
            } catch (err) {
              console.warn("Failed to restore conversation messages:", err);
            }
          }
        }
      }
    } catch {
      // Ignore transient errors
    }
  }, [repo.repo_id]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // Synchronize incoming activeFixTask into chronological message list
  useEffect(() => {
    if (!activeFixTask) return;
    setMessages((prev) => {
      const existingIdx = prev.findIndex((m) => m.fixTask?.taskId === activeFixTask.taskId);
      if (existingIdx !== -1) {
        const next = [...prev];
        next[existingIdx] = {
          ...next[existingIdx],
          fixTask: activeFixTask,
        };
        return next;
      }

      const taskMessage: ChatMessage = {
        id: `task-msg-${activeFixTask.taskId}`,
        role: "assistant",
        content: `I've inspected the issue **[${activeFixTask.errorReport.rule_id}]** in \`${activeFixTask.errorReport.file_path}\`.`,
        fixTask: activeFixTask,
      };
      return [...prev, taskMessage];
    });
  }, [activeFixTask]);

  const handleNewChat = async () => {
    if (activeAbortControllerRef.current) {
      try { activeAbortControllerRef.current.abort(); } catch {}
      activeAbortControllerRef.current = null;
    }
    activeRequestIdRef.current += 1;
    setIsStreaming(false);
    setQueuedMessage(null);

    try {
      const newConv = await createConversation(
        repo.repo_id,
        "CodeBrain Issue Resolution Workflow",
        selectedModel.providerId,
        selectedModel.id
      );
      setActiveConvId(newConv.id);
      try {
        localStorage.setItem(`codebrain_active_conv_${repo.repo_id}`, newConv.id);
      } catch {}
      setConversations((prev) => [newConv, ...prev.filter((c) => c.id !== newConv.id)]);
      setMessages([
        {
          id: `welcome-${Date.now()}`,
          role: "assistant",
          content: getWelcomeMessageContent(repo?.name),
        },
      ]);
      setIsHistoryOpen(false);
      setIsMoreMenuOpen(false);
    } catch (err: any) {
      console.error("Failed to start new chat:", err);
    }
  };

  const handleSelectConversation = async (conv: ConversationItem) => {
    if (activeAbortControllerRef.current) {
      try { activeAbortControllerRef.current.abort(); } catch {}
      activeAbortControllerRef.current = null;
    }
    activeRequestIdRef.current += 1;
    setIsStreaming(false);
    setQueuedMessage(null);

    try {
      setActiveConvId(conv.id);
      try {
        localStorage.setItem(`codebrain_active_conv_${repo.repo_id}`, conv.id);
      } catch {}
      setIsHistoryOpen(false);
      const full = await fetchConversation(repo.repo_id, conv.id);
      if (full && full.messages && full.messages.length > 0) {
        setMessages(
          full.messages.map((m: any) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            errorReports: m.error_reports,
          }))
        );
      } else {
        setMessages([
          {
            id: `resumed-${Date.now()}`,
            role: "assistant",
            content: `Resumed conversation "${conv.title}".`,
          },
        ]);
      }
    } catch (err: any) {
      console.error("Failed to load conversation:", err);
    }
  };

  const handleDeleteConversation = async (e: React.MouseEvent, convId: string) => {
    e.stopPropagation();
    try {
      await deleteConversation(repo.repo_id, convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConvId === convId) {
        setActiveConvId(null);
        try {
          localStorage.removeItem(`codebrain_active_conv_${repo.repo_id}`);
        } catch {}
      }
    } catch (err) {
      console.error("Failed to delete chat:", err);
    }
  };

  useEffect(() => {
    refreshApinexQuota();
    const pollTimer = setInterval(refreshApinexQuota, 4000);
    const onQuotaUpdate = () => refreshApinexQuota();
    window.addEventListener("apinex-quota-updated", onQuotaUpdate);

    fetchAiRegistry()
      .then((res) => {
        if (res && res.providers) {
          const loadedModels: ChatModelOption[] = [];
          const seen = new Set<string>();

          const providerOrder = ["nvidia", "groq", "apinex", "openai-compatible", "anthropic-compatible"];
          const sortedProviderKeys = Object.keys(res.providers).sort((a, b) => {
            const idxA = providerOrder.indexOf(a);
            const idxB = providerOrder.indexOf(b);
            const pA = idxA !== -1 ? idxA : 99;
            const pB = idxB !== -1 ? idxB : 99;
            return pA - pB;
          });

          for (const provKey of sortedProviderKeys) {
            const prov = res.providers[provKey];
            if (!prov || !prov.models) continue;
            for (const m of prov.models) {
              const uniqueKey = `${m.providerId}:${m.id}`;
              if (seen.has(uniqueKey)) continue;
              seen.add(uniqueKey);

              const modelDisplayName = m.displayName || m.name || m.id;
              const providerDisplayName = m.providerDisplayName || prov.displayName;

              loadedModels.push({
                id: m.id,
                displayName: modelDisplayName,
                name: modelDisplayName,
                providerId: m.providerId,
                providerDisplayName: providerDisplayName,
                provider: m.providerId as any,
                providerLabel: providerDisplayName,
                badge: m.badge || (m.recommendedFor ? m.recommendedFor.toUpperCase() : "AVAILABLE"),
                capabilities: m.capabilities || [],
                status: m.status,
              });
            }
          }

          if (loadedModels.length > 0) {
            const allModels = [AUTO_MODEL_OPTION, ...loadedModels];
            setAvailableModels(allModels);
            fetchApiKeyStatus()
              .then((status) => {
                if (
                  status &&
                  status.preferred_ai_provider &&
                  (status.preferred_ai_provider === "openai-compatible" ||
                    status.preferred_ai_provider === "anthropic-compatible" ||
                    status.preferred_ai_provider === "custom")
                ) {
                  const targetProv =
                    status.preferred_ai_provider === "custom"
                      ? "openai-compatible"
                      : status.preferred_ai_provider;
                  const targetModel = status.preferred_ai_model;
                  const customMatch = allModels.find(
                    (m) =>
                      m.providerId === targetProv &&
                      (!targetModel || m.id === targetModel)
                  );
                  if (customMatch) {
                    setSelectedModel(customMatch);
                    return;
                  }
                }

                try {
                  const savedProv = localStorage.getItem("codebrain_selected_ai_provider");
                  const savedModel = localStorage.getItem("codebrain_selected_ai_model");
                  if (savedProv === "auto" || savedModel === "auto") {
                    setSelectedModel(AUTO_MODEL_OPTION);
                    return;
                  }
                  if (savedProv && savedModel) {
                    const found = allModels.find((m) => m.providerId === savedProv && m.id === savedModel);
                    if (found) {
                      setSelectedModel(found);
                      return;
                    }
                  }
                } catch {}
              })
              .catch(() => {
                try {
                  const savedProv = localStorage.getItem("codebrain_selected_ai_provider");
                  const savedModel = localStorage.getItem("codebrain_selected_ai_model");
                  if (savedProv === "auto" || savedModel === "auto") {
                    setSelectedModel(AUTO_MODEL_OPTION);
                    return;
                  }
                  if (savedProv && savedModel) {
                    const found = allModels.find((m) => m.providerId === savedProv && m.id === savedModel);
                    if (found) {
                      setSelectedModel(found);
                      return;
                    }
                  }
                } catch {}
              });

            setSelectedModel((prev) => {
              if (prev.id === "auto" || prev.providerId === "auto") {
                return AUTO_MODEL_OPTION;
              }
              const matching = allModels.find(
                (m) => m.id === prev.id && m.providerId === prev.providerId
              );
              return matching || AUTO_MODEL_OPTION;
            });
          }
        }
      })
      .catch(() => {});

    return () => {
      clearInterval(pollTimer);
      window.removeEventListener("apinex-quota-updated", onQuotaUpdate);
    };
  }, []);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isNearBottomRef.current = distanceToBottom < 80;
  }, []);

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollContainerRef.current;
    if (!el) {
      bottomRef.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto" });
      return;
    }
    if (!isNearBottomRef.current) return;
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  const prevMessagesLengthRef = useRef(messages.length);
  useEffect(() => {
    if (messages.length !== prevMessagesLengthRef.current) {
      prevMessagesLengthRef.current = messages.length;
      if (isNearBottomRef.current) {
        scrollToBottom(true);
      }
    }
  }, [messages.length, scrollToBottom]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(e.target as Node)) {
        setIsModelMenuOpen(false);
      }
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) {
        setIsMoreMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedImage(file);
      const url = URL.createObjectURL(file);
      setImagePreviewUrl(url);
    }
  };

  const clearSelectedImage = useCallback(() => {
    setSelectedImage(null);
    if (imagePreviewUrl) {
      URL.revokeObjectURL(imagePreviewUrl);
      setImagePreviewUrl(null);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [imagePreviewUrl]);

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile();
        if (file) {
          setSelectedImage(file);
          setImagePreviewUrl(URL.createObjectURL(file));
          break;
        }
      }
    }
  };

  const handleStop = useCallback(() => {
    activeRequestIdRef.current += 1;
    if (activeAbortControllerRef.current) {
      try {
        activeAbortControllerRef.current.abort();
      } catch {}
      activeAbortControllerRef.current = null;
    }
    setMessages((prev) =>
      prev.map((m) =>
        m.isStreaming
          ? {
              ...m,
              isStreaming: false,
              isStopped: true,
            }
          : m
      )
    );
    setIsStreaming(false);
  }, []);

  const handleQueueMessage = useCallback(() => {
    if (!input.trim() && !selectedImage) return;
    const queued: QueuedMessage = {
      id: `queue-${Date.now()}`,
      query: input.trim(),
      image: selectedImage,
    };
    setQueuedMessage(queued);
    setInput("");
    clearSelectedImage();
  }, [input, selectedImage, clearSelectedImage]);

  const handleEditQueued = useCallback(() => {
    if (!queuedMessage) return;
    setInput(queuedMessage.query);
    if (queuedMessage.image) {
      setSelectedImage(queuedMessage.image);
      setImagePreviewUrl(URL.createObjectURL(queuedMessage.image));
    }
    setQueuedMessage(null);
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [queuedMessage]);

  const handleCancelQueued = useCallback(() => {
    setQueuedMessage(null);
  }, []);

  const handleSend = useCallback(
    async (overrideQuery?: string, shouldSpeak = false, overrideImage?: File) => {
      const imgToUse = overrideImage !== undefined ? overrideImage : selectedImage;
      const rawQuery = overrideQuery !== undefined ? overrideQuery : input;
      if (!rawQuery.trim() && !imgToUse) return;

      // If already generating, immediately abort the previous stream before launching new one
      if (activeAbortControllerRef.current) {
        try {
          activeAbortControllerRef.current.abort();
        } catch {}
        activeAbortControllerRef.current = null;
      }
      setMessages((prev) =>
        prev.map((m) =>
          m.isStreaming
            ? { ...m, isStreaming: false, isStopped: true }
            : m
        )
      );

      const abortController = new AbortController();
      activeAbortControllerRef.current = abortController;
      const currentReqId = ++activeRequestIdRef.current;

      const userMsgId = `user-${Date.now()}`;
      const assistantMsgId = `asst-${Date.now()}`;
      const userMsg: ChatMessage = {
        id: userMsgId,
        role: "user",
        content: rawQuery.trim(),
        imageUrl: imgToUse ? URL.createObjectURL(imgToUse) : undefined,
      };
      const assistantPlaceholder: ChatMessage = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
      if (overrideQuery === undefined) setInput("");
      clearSelectedImage();
      setIsStreaming(true);
      speakOnDoneRef.current = shouldSpeak;

      const queryToSend = activeFilePath
        ? `[Active File: ${activeFilePath}]\n${rawQuery.trim()}`
        : rawQuery.trim();

      let accumulatedAnswer = "";
      let errorReports: ErrorReport[] = [];

      let targetConvId = activeConvId;
      if (!targetConvId) {
        try {
          const fresh = await createConversation(
            repo.repo_id,
            rawQuery.trim().slice(0, 35) || "New Conversation",
            selectedModel.providerId,
            selectedModel.id
          );
          if (currentReqId === activeRequestIdRef.current) {
            targetConvId = fresh.id;
            setActiveConvId(fresh.id);
            setConversations((prev) => [fresh, ...prev.filter((c) => c.id !== fresh.id)]);
          }
        } catch {}
      }

      if (targetConvId) {
        addConversationMessage(repo.repo_id, targetConvId, "user", rawQuery.trim()).catch(() => {});
      }

      try {
        const isAuto = !selectedModel || selectedModel.id === "auto" || selectedModel.providerId === "auto";
        const providerParam = isAuto ? undefined : (selectedModel.providerId || selectedModel.provider);
        const modelParam = isAuto ? undefined : selectedModel.id;

        let pendingAnswer = "";
        let rafId: number | null = null;
        let lastPaintTime = 0;

        const flushTokens = () => {
          if (currentReqId !== activeRequestIdRef.current) return;
          accumulatedAnswer = pendingAnswer;
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantMsgId ? { ...m, content: accumulatedAnswer } : m))
          );
          scrollToBottom(false);
          rafId = null;
          lastPaintTime = performance.now();
        };

        const scheduleFlush = () => {
          const now = performance.now();
          if (now - lastPaintTime >= 35) {
            flushTokens();
          } else if (!rafId) {
            rafId = requestAnimationFrame(flushTokens);
          }
        };

        await streamAsk(
          repo.repo_id,
          queryToSend,
          8,
          {
            onCitations: () => {},
            onErrorReports: (e) => {
              if (currentReqId !== activeRequestIdRef.current) return;
              errorReports = e;
              setMessages((prev) =>
                prev.map((m) => (m.id === assistantMsgId ? { ...m, errorReports: e } : m))
              );
            },
            onStatus: (s) => {
              if (currentReqId !== activeRequestIdRef.current) return;
              if (
                s &&
                (s.includes("APInex GPT-6 Luna has reached its daily token limit") ||
                  s.includes("switched to another available AI model"))
              ) {
                setMessages((prev) =>
                  prev.map((m) => (m.id === assistantMsgId ? { ...m, fallbackNotice: s } : m))
                );
              } else {
                setMessages((prev) =>
                  prev.map((m) => (m.id === assistantMsgId ? { ...m, analysisStatus: s } : m))
                );
              }
            },
            onToken: (t) => {
              if (currentReqId !== activeRequestIdRef.current) return;
              pendingAnswer += t;
              scheduleFlush();
            },
            onDone: () => {
              if (currentReqId !== activeRequestIdRef.current) return;
              if (rafId) {
                cancelAnimationFrame(rafId);
                rafId = null;
              }
              refreshApinexQuota();
              accumulatedAnswer = pendingAnswer;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, content: accumulatedAnswer, isStreaming: false, errorReports }
                    : m
                )
              );
              setIsStreaming(false);
              activeAbortControllerRef.current = null;
              scrollToBottom(true);
              if (targetConvId && accumulatedAnswer) {
                addConversationMessage(
                  repo.repo_id,
                  targetConvId,
                  "assistant",
                  accumulatedAnswer,
                  undefined,
                  errorReports
                )
                  .then(() => loadConversations())
                  .catch(() => {});
              }
              if (speakOnDoneRef.current && accumulatedAnswer) {
                speakResponse(accumulatedAnswer);
                speakOnDoneRef.current = false;
              }

              // Auto-dispatch next queued message if waiting
              if (queuedMessageRef.current) {
                const next = queuedMessageRef.current;
                setQueuedMessage(null);
                setTimeout(() => {
                  handleSend(next.query, false, next.image || undefined);
                }, 50);
              }
            },
            onStop: () => {
              if (currentReqId !== activeRequestIdRef.current) return;
              if (rafId) {
                cancelAnimationFrame(rafId);
                rafId = null;
              }
              accumulatedAnswer = pendingAnswer;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, content: accumulatedAnswer, isStreaming: false, isStopped: true }
                    : m
                )
              );
              setIsStreaming(false);
              activeAbortControllerRef.current = null;
              if (targetConvId && accumulatedAnswer) {
                addConversationMessage(
                  repo.repo_id,
                  targetConvId,
                  "assistant",
                  accumulatedAnswer,
                  undefined,
                  errorReports
                )
                  .then(() => loadConversations())
                  .catch(() => {});
              }

              // Auto-dispatch next queued message if user wanted Stop & Send
              if (queuedMessageRef.current) {
                const next = queuedMessageRef.current;
                setQueuedMessage(null);
                setTimeout(() => {
                  handleSend(next.query, false, next.image || undefined);
                }, 50);
              }
            },
            onError: (err) => {
              if (currentReqId !== activeRequestIdRef.current) return;
              if (rafId) {
                cancelAnimationFrame(rafId);
                rafId = null;
              }
              accumulatedAnswer = pendingAnswer;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, content: accumulatedAnswer || `⚠️ ${err || "An error occurred while connecting to AI providers."}`, isStreaming: false }
                    : m
                )
              );
              setIsStreaming(false);
              activeAbortControllerRef.current = null;
            },
          },
          imgToUse ?? undefined,
          providerParam,
          modelParam,
          abortController.signal
        );
      } catch (err: any) {
        if (currentReqId !== activeRequestIdRef.current) return;
        if (abortController.signal.aborted || err?.name === "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, isStreaming: false, isStopped: true }
                : m
            )
          );
        } else {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: accumulatedAnswer || `⚠️ ${err?.message || "Failed to communicate with AI service."}`, isStreaming: false }
                : m
            )
          );
        }
        setIsStreaming(false);
        activeAbortControllerRef.current = null;
      }
    },
    [input, selectedImage, repo.repo_id, activeFilePath, selectedModel, activeConvId, loadConversations, clearSelectedImage]
  );

  const handleStopAndSendQueued = useCallback(() => {
    if (!queuedMessage) return;
    const target = queuedMessage;
    setQueuedMessage(null);
    handleStop();
    setTimeout(() => {
      handleSend(target.query, false, target.image || undefined);
    }, 20);
  }, [queuedMessage, handleStop, handleSend]);

  const handleVoiceTranscribed = (result: TranscribeResponse) => {
    setVoiceHint(result.text);
    setTimeout(() => setVoiceHint(null), 4000);
    handleSend(result.text, true);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (isStreaming) {
        handleQueueMessage();
      } else {
        handleSend();
      }
    }
  };

  // Auto-resize textarea dynamically based on content up to 160px max height
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    if (!input.trim()) {
      el.style.height = "22px";
    } else {
      el.style.height = "0px";
      const targetHeight = Math.min(Math.max(el.scrollHeight, 22), 160);
      el.style.height = `${targetHeight}px`;
    }
  }, [input]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    if (!e.target.value.trim()) {
      el.style.height = "22px";
    } else {
      el.style.height = "0px";
      const targetHeight = Math.min(Math.max(el.scrollHeight, 22), 160);
      el.style.height = `${targetHeight}px`;
    }
  };

  return (
    <div className="flex flex-col h-full w-full bg-[#0c0d0e] text-[#cccccc] overflow-hidden">
      {/* ── Compact Header (Matching Reference Screenshot) ─────────────────────── */}
      <div className="h-10 px-3 bg-[#0c0d0e] border-b border-[#1e1f22] flex items-center justify-between text-xs shrink-0 z-20 select-none">
        <div className="flex items-center gap-2 min-w-0 pr-2">
          <span
            className="font-medium text-white text-xs truncate max-w-[210px] sm:max-w-[280px]"
            title={activeConvTitle}
          >
            {activeConvTitle}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0 text-gray-400">
          {/* New Chat Button */}
          <button
            type="button"
            onClick={handleNewChat}
            title="New Chat"
            className="p-1.5 hover:text-white hover:bg-[#1a1b1e] rounded transition-colors"
          >
            <Plus size={15} />
          </button>

          {/* Recent Chats Button */}
          <button
            type="button"
            onClick={() => setIsHistoryOpen((prev) => !prev)}
            title={`Recent Conversations (${conversations.length})`}
            className={`p-1.5 hover:text-white hover:bg-[#1a1b1e] rounded transition-colors relative ${
              isHistoryOpen ? "text-purple-400 bg-[#1a1b1e]" : ""
            }`}
          >
            <History size={14} />
          </button>

          {/* More Options Menu */}
          <div className="relative" ref={moreMenuRef}>
            <button
              type="button"
              onClick={() => setIsMoreMenuOpen((prev) => !prev)}
              title="More options"
              className="p-1.5 hover:text-white hover:bg-[#1a1b1e] rounded transition-colors"
            >
              <MoreHorizontal size={15} />
            </button>

            {isMoreMenuOpen && (
              <div className="absolute top-full right-0 mt-1 w-48 bg-[#0c0d0e] border border-[#1e1f22] rounded-lg shadow-xl p-1 z-50 text-xs select-none">
                <button
                  type="button"
                  onClick={() => {
                    setMessages([
                      {
                        id: `cleared-${Date.now()}`,
                        role: "assistant",
                        content: getWelcomeMessageContent(repo?.name),
                      },
                    ]);
                    setIsMoreMenuOpen(false);
                  }}
                  className="w-full text-left px-2 py-1.5 rounded hover:bg-[#1a1b1e] text-gray-300 hover:text-white transition-colors"
                >
                  Clear messages
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const text = messages.map((m) => `${m.role.toUpperCase()}: ${m.content}`).join("\n\n");
                    navigator.clipboard.writeText(text);
                    setIsMoreMenuOpen(false);
                  }}
                  className="w-full text-left px-2 py-1.5 rounded hover:bg-[#1a1b1e] text-gray-300 hover:text-white transition-colors"
                >
                  Copy conversation
                </button>
              </div>
            )}
          </div>

          {/* Close Panel Button */}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              title="Close Chat Panel"
              className="p-1.5 hover:text-white hover:bg-[#1a1b1e] rounded transition-colors"
            >
              <X size={15} />
            </button>
          )}
        </div>

        {/* Recent Conversations Dropdown */}
        {isHistoryOpen && (
          <div className="absolute top-10 right-3 w-72 bg-[#0c0d0e] border border-[#1e1f22] rounded-xl shadow-2xl p-2 z-50 text-xs space-y-1.5 max-h-80 overflow-y-auto">
            <div className="px-2 py-1 text-[10px] text-gray-400 font-bold uppercase tracking-wider border-b border-[#1e1f22] flex items-center justify-between">
              <span>Recent Conversations</span>
              <span className="font-mono text-purple-400">{conversations.length} total</span>
            </div>
            {conversations.length === 0 ? (
              <div className="p-4 text-center text-gray-500 text-xs">No saved conversations yet.</div>
            ) : (
              conversations.map((c) => (
                <div
                  key={c.id}
                  onClick={() => handleSelectConversation(c)}
                  className={`p-2 rounded-lg cursor-pointer flex items-center justify-between gap-2 transition-colors border ${
                    activeConvId === c.id
                      ? "bg-purple-950/30 border-purple-500/50 text-white"
                      : "hover:bg-[#1a1b1e] border-transparent text-gray-300"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-xs truncate">{c.title || "Conversation"}</p>
                    <p className="text-[10px] text-gray-500 truncate mt-0.5">
                      {c.last_message_preview || new Date(c.updated_at).toLocaleDateString()}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => handleDeleteConversation(e, c.id)}
                    title="Delete chat"
                    className="p-1 text-gray-500 hover:text-red-400 rounded transition-colors"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* ── Chronological Message History ────────────────────────────────────── */}
      <div ref={scrollContainerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-3.5 py-3 min-h-0 space-y-4 chat-selectable select-text bg-[#0c0d0e]">
        {messages.map((message) => {
          if (message.role === "user") {
            return (
              <div key={message.id} className="w-full chat-selectable select-text">
                <div className="bg-[#0c0d0e] border border-[#1e1f22] rounded-xl p-3.5 text-gray-100 text-[14px] leading-[1.6] shadow-sm space-y-3 break-words chat-selectable select-text cursor-text">
                  {message.images && message.images.length > 0 && (
                    <div className="flex items-center gap-2 overflow-x-auto pb-1 select-none">
                      {message.images.map((img, idx) => (
                        <img
                          key={idx}
                          src={img}
                          alt={`Attachment ${idx + 1}`}
                          className="h-16 w-16 sm:h-20 sm:w-20 rounded-lg border border-[#2e3344] object-cover bg-black/40 shrink-0"
                        />
                      ))}
                    </div>
                  )}
                  {message.imageUrl && !message.images && (
                    <div className="flex items-center gap-2 overflow-x-auto pb-1 select-none">
                      <img
                        src={message.imageUrl}
                        alt="Uploaded screenshot"
                        className="h-16 w-16 sm:h-20 sm:w-20 rounded-lg border border-[#2e3344] object-cover bg-black/40 shrink-0"
                      />
                    </div>
                  )}
                  {message.content && (
                    <div className="text-gray-100 font-medium select-text">
                      <MarkdownRenderer content={message.content} />
                    </div>
                  )}
                </div>
              </div>
            );
          }

          return (
            <div key={message.id} className="flex flex-col gap-2 max-w-full chat-selectable select-text">
              {/* Automatic Fallback Notification Banner */}
              {message.fallbackNotice && (
                <div className="px-3 py-2 rounded-lg bg-amber-950/40 border border-amber-600/50 text-amber-200 text-xs flex items-center gap-2 select-none shadow-sm">
                  <span className="text-amber-400 font-bold shrink-0 text-sm">⚠️</span>
                  <span className="font-medium">{message.fallbackNotice}</span>
                </div>
              )}

              {/* Text / Markdown message */}
              {(message.content || message.isStreaming) && (
                <div className="text-gray-200 text-[14px] leading-[1.65] font-normal break-words chat-selectable select-text cursor-text">
                  {message.isStreaming && !message.content ? (
                    <div className="inline-flex items-center gap-2 py-1 select-none text-xs text-gray-400">
                      <span className="flex gap-1 items-center text-blue-400">
                        <span className="animate-pulse">●</span>
                        <span className="animate-pulse delay-75">●</span>
                        <span className="animate-pulse delay-150">●</span>
                      </span>
                      {message.analysisStatus && (
                        <span className="font-mono text-xs text-gray-300">
                          {message.analysisStatus}
                        </span>
                      )}
                    </div>
                  ) : (
                    <div className="select-text">
                      <MarkdownRenderer content={message.content} />
                      {message.isStreaming && (
                        <span className="inline-block w-1.5 h-4 bg-blue-400 ml-0.5 animate-pulse rounded-sm align-middle select-none" />
                      )}
                      {message.isStopped && (
                        <div className="mt-2 flex items-center gap-1.5 text-xs select-none">
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-950/40 border border-amber-800/40 text-amber-400 font-mono text-[11px]">
                            <Square size={8} className="fill-current text-amber-400" />
                            <span>Stopped by user</span>
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Task Work Log Card (Chronological) */}
              {message.fixTask && (
                <div className="bg-[#0c0d0e] border border-[#1e1f22] rounded-xl p-3 shadow-lg space-y-2.5 animate-fade-in text-xs">
                  <div className="flex items-center justify-between border-b border-[#1e1f22] pb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[10px] bg-purple-950/40 text-purple-300 border border-purple-800 font-mono px-1.5 py-0.5 rounded shrink-0">
                        TASK #{message.fixTask.taskId.slice(0, 8)}
                      </span>
                      <span className="text-xs font-bold text-white truncate">
                        {message.fixTask.errorReport?.rule_id || "TASK"}: {message.fixTask.errorReport?.file_path || "Issue Fix"}
                      </span>
                    </div>
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded-full uppercase border shrink-0 ${
                        message.fixTask.stage === "READY"
                          ? "bg-emerald-950 text-emerald-300 border-emerald-800"
                          : message.fixTask.stage === "APPLIED"
                          ? "bg-purple-950 text-purple-300 border-purple-800"
                          : message.fixTask.stage === "FAILED"
                          ? "bg-red-950 text-red-300 border-red-800"
                          : message.fixTask.stage === "REJECTED"
                          ? "bg-gray-800 text-gray-400 border-gray-700"
                          : "bg-blue-950 text-blue-300 border-blue-800 animate-pulse"
                      }`}
                    >
                      {message.fixTask.stage}
                    </span>
                  </div>

                  {/* Work Log Timeline */}
                  <div className="space-y-1.5 text-xs font-mono">
                    {message.fixTask.log
                      .filter((entry) => !entry.step.toLowerCase().includes("validation"))
                      .map((entry, idx) => (
                      <div key={idx} className="flex items-start gap-2 text-[#999999]">
                        <span className="text-[10px] text-gray-500 shrink-0">{entry.timestamp}</span>
                        <span
                          className={`shrink-0 ${
                            entry.status === "done"
                              ? "text-emerald-400"
                              : entry.status === "info"
                              ? "text-blue-400 font-bold"
                              : entry.status === "running"
                              ? "text-blue-400 animate-pulse"
                              : entry.status === "error"
                              ? "text-red-400"
                              : "text-gray-500"
                          }`}
                        >
                          {entry.status === "done" ? "✓" : entry.status === "info" ? "ℹ" : entry.status === "running" ? "●" : entry.status === "error" ? "✗" : "○"}
                        </span>
                        <div className="min-w-0 flex-1 break-words">
                          <span className="font-semibold text-gray-300">{entry.step}: </span>
                          <span className="text-gray-400">{entry.detail}</span>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Changed Files */}
                  {message.fixTask.changed_files && message.fixTask.changed_files.length > 0 && (
                    <div className="p-2 bg-[#0c0d0e] rounded-lg border border-[#1e1f22] flex items-center justify-between text-xs font-mono">
                      <span className="text-gray-400">Target File:</span>
                      <span className="text-gray-200 truncate font-semibold" title={message.fixTask.changed_files.join(", ")}>
                        {message.fixTask.changed_files[0]}
                      </span>
                    </div>
                  )}

                  {/* Diff line stats */}
                  {message.fixTask.diff && (
                    <div className="p-2 bg-[#0c0d0e] rounded-lg border border-[#1e1f22] flex items-center justify-between text-xs font-mono">
                      <span className="text-gray-400">Changed Diff:</span>
                      <div className="flex items-center gap-2">
                        <span className="text-emerald-400 font-bold">+{message.fixTask.linesAdded ?? 0}</span>
                        <span className="text-red-400 font-bold">-{message.fixTask.linesDeleted ?? 0}</span>
                        <span className="text-gray-500">lines</span>
                      </div>
                    </div>
                  )}

                  {/* Controls */}
                  <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#1e1f22]">
                    {onReviewDiff && message.fixTask.diff && (
                      <button
                        type="button"
                        onClick={() => onReviewDiff(message.fixTask!)}
                        className="px-2.5 py-1 bg-[#0c0d0e] hover:bg-[#1a1b1e] text-gray-300 rounded-md text-xs font-medium border border-[#1e1f22] transition-colors"
                      >
                        Review Diff
                      </button>
                    )}
                    {onRejectFix && message.fixTask.stage === "READY" && (
                      <button
                        type="button"
                        onClick={() => onRejectFix(message.fixTask!)}
                        className="px-2.5 py-1 bg-red-950/60 hover:bg-red-900/80 text-red-300 rounded-md text-xs font-medium border border-red-800 transition-colors"
                      >
                        Reject
                      </button>
                    )}
                    {onApplyFix && message.fixTask.stage === "READY" && (
                      <button
                        type="button"
                        onClick={() => onApplyFix(message.fixTask!)}
                        className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-md text-xs font-semibold shadow transition-all flex items-center gap-1"
                      >
                        <Check size={12} />
                        <span>Accept & Apply</span>
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Detected Issue Fixes */}
              {message.errorReports && message.errorReports.length > 0 && !message.isStreaming && (
                <div className="mt-1 space-y-2">
                  <p className="text-xs text-amber-400 font-semibold flex items-center gap-1.5 ml-1">
                    <span>⚡</span>
                    <span>Detected Issue Fix ({message.errorReports.length})</span>
                  </p>
                  <div className="space-y-3">
                    {message.errorReports.map((report) => (
                      <ErrorSuggestionCard key={report.id} report={report} repoId={repo.repo_id} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        <div ref={bottomRef} />
      </div>

      {/* ── Fixed Bottom Area: Review Dock + Composer ─────────────────────────── */}
      <div className="shrink-0 border-t border-[#1e1f22] bg-[#0c0d0e] px-3 pt-2 pb-3 space-y-2">
        {/* Compact Review Action Bar (attached directly above composer) */}
        {pendingFiles.length === 0 ? (
          <div className="flex items-center justify-between text-xs text-gray-500 px-1 py-0.5">
            <div className="flex items-center gap-1.5 select-none">
              <ArrowLeft size={13} className="text-gray-500" />
              <FileText size={13} className="text-gray-500" />
              <span className="font-medium text-gray-400">0 Files With Changes</span>
            </div>
            <button
              type="button"
              disabled
              className="flex items-center gap-1.5 px-3 py-1 bg-[#0c0d0e] text-gray-500 border border-[#1e1f22] rounded-lg text-xs font-medium cursor-not-allowed"
            >
              <FileText size={12} className="text-gray-600" />
              <span>Review Changes</span>
            </button>
          </div>
        ) : (
          <div className="space-y-1.5">
            {/* Expanded changed files list when open */}
            {isChangedFilesExpanded && (
              <div className="bg-[#0c0d0e] border border-[#1e1f22] rounded-xl overflow-hidden divide-y divide-[#1e1f22] text-xs shadow-inner max-h-48 overflow-y-auto">
                {pendingFiles.map((file, idx) => (
                  <div
                    key={idx}
                    onClick={() => onReviewDiff && onReviewDiff(activeFixTask!, file.path, file.diff)}
                    className="flex items-center justify-between px-3 py-2 hover:bg-[#1a1b1e] cursor-pointer group transition-colors"
                    title={`Click to review ${file.path}`}
                  >
                    <div className="flex items-center gap-2 min-w-0 pr-2">
                      <FileCode size={13} className="text-gray-400 group-hover:text-amber-400 shrink-0 transition-colors" />
                      <div className="flex items-center gap-1.5 font-mono text-[11px] shrink-0">
                        <span className="text-emerald-400 font-bold">+{file.linesAdded}</span>
                        <span className="text-rose-400 font-bold">-{file.linesDeleted}</span>
                      </div>
                      <span className="text-gray-200 group-hover:text-white font-medium truncate">{file.name}</span>
                      <span className="text-[10px] text-gray-500 truncate hidden sm:inline">{file.path}</span>
                    </div>

                    <ChevronRight size={12} className="text-gray-600 group-hover:text-purple-400 shrink-0 transition-colors" />
                  </div>
                ))}
              </div>
            )}

            {/* Pending changes summary row */}
            <div className="flex items-center justify-between text-xs text-gray-400 px-1 py-0.5">
              <div
                className="flex items-center gap-1.5 cursor-pointer hover:text-white transition-colors select-none"
                onClick={() => setIsChangedFilesExpanded((prev) => !prev)}
              >
                <ChevronRight
                  size={13}
                  className={`text-gray-500 transition-transform ${isChangedFilesExpanded ? "rotate-90" : ""}`}
                />
                <span className="font-semibold text-gray-200">
                  {pendingFiles.length} file{pendingFiles.length > 1 ? "s" : ""} changed
                </span>
                <span className="font-mono text-xs flex items-center gap-1 ml-1">
                  <span className="text-emerald-400 font-bold">+{totalLinesChanged.added}</span>
                  <span className="text-rose-400 font-bold">-{totalLinesChanged.deleted}</span>
                </span>
              </div>

              <div className="flex items-center gap-2">
                {onRejectFix && activeFixTask && activeFixTask.stage === "READY" && (
                  <button
                    type="button"
                    onClick={() => onRejectFix(activeFixTask)}
                    className="px-2.5 py-1 text-gray-300 hover:text-red-400 hover:bg-red-950/30 rounded text-xs transition-colors"
                  >
                    Reject all
                  </button>
                )}

                {onApplyFix && activeFixTask && activeFixTask.stage === "READY" && (
                  <button
                    type="button"
                    onClick={() => onApplyFix(activeFixTask)}
                    className="flex items-center gap-1.5 px-3 py-1 bg-purple-600 hover:bg-purple-500 text-white rounded font-medium text-xs shadow-md transition-colors"
                  >
                    <span>Accept all</span>
                    <ChevronDown size={12} />
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => {
                    if (activeFixTask && onReviewDiff) {
                      onReviewDiff(activeFixTask);
                    }
                  }}
                  className="flex items-center gap-1.5 px-3 py-1 bg-[#0c0d0e] hover:bg-[#1a1b1e] text-gray-300 hover:text-white border border-[#1e1f22] rounded-lg text-xs font-medium transition-colors"
                >
                  <FileText size={12} className="text-gray-400" />
                  <span>Review Changes</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {voiceHint && (
          <div className="flex items-center gap-2 text-xs text-purple-300 bg-purple-950/40 border border-purple-800/50 rounded-xl px-3 py-1.5 animate-fade-in">
            <span className="opacity-70">Detected speech:</span>
            <span className="font-medium">{voiceHint}</span>
          </div>
        )}

        {imagePreviewUrl && (
          <div className="relative inline-block">
            <img
              src={imagePreviewUrl}
              alt="Preview"
              className="h-16 rounded-lg border border-[#1e1f22] object-cover bg-black/40"
            />
            <button
              type="button"
              onClick={clearSelectedImage}
              className="absolute -top-1.5 -right-1.5 bg-red-600 hover:bg-red-500 text-white rounded-full p-0.5 shadow-md"
            >
              <X size={10} />
            </button>
          </div>
        )}

        {/* Queued Next Message Banner */}
        {queuedMessage && (
          <div className="bg-[#0c0d0e] border border-purple-500/40 rounded-xl px-3 py-2 flex items-center justify-between gap-3 text-xs shadow-md animate-fade-in mb-2">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="flex items-center gap-1 font-semibold text-purple-400 shrink-0">
                <Clock size={13} className="text-purple-400" />
                <span>Queued next:</span>
              </span>
              <span className="text-gray-300 truncate font-mono text-[12px]">{queuedMessage.query}</span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                onClick={handleStopAndSendQueued}
                className="px-2 py-1 bg-purple-600 hover:bg-purple-500 text-white rounded-md text-[11px] font-medium transition-colors"
                title="Stop current response and send queued message now"
              >
                Stop & Send Now
              </button>
              <button
                type="button"
                onClick={handleEditQueued}
                className="px-2 py-1 bg-[#141518] hover:bg-[#1a1b1e] text-gray-300 hover:text-white rounded-md text-[11px] transition-colors"
                title="Edit queued message"
              >
                Edit
              </button>
              <button
                type="button"
                onClick={handleCancelQueued}
                className="p-1 text-gray-400 hover:text-red-400 hover:bg-[#141518] rounded-md transition-colors"
                title="Cancel queued message"
              >
                <X size={13} />
              </button>
            </div>
          </div>
        )}

        {/* Composer Box (Matching Reference Screenshot) */}
        <div className="bg-[#0c0d0e] border border-[#1e1f22] rounded-2xl px-3 pt-2 pb-2 shadow-lg focus-within:border-purple-500/60 transition-colors flex flex-col">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleImageChange}
            accept="image/*"
            className="hidden"
          />

          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={
              isStreaming
                ? "Type next message (Enter to queue)..."
                : "Ask anything, @ to mention, / for actions"
            }
            rows={1}
            style={{ height: "22px" }}
            className="w-full bg-[#0c0d0e] text-sm text-white placeholder-gray-500 resize-none outline-none leading-5 min-h-[22px] max-h-[160px] overflow-y-auto block p-0"
          />

          {/* Composer Footer: + Model Selector    [mic] [arrow / stop] */}
          <div className="flex items-center justify-between gap-2 mt-1.5 shrink-0">
            <div className="flex items-center gap-1.5 relative" ref={modelMenuRef}>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                title="Attach screenshot or file"
                className="p-1 text-gray-400 hover:text-white hover:bg-[#1a1b1e] rounded-md transition-colors"
              >
                <Plus size={15} />
              </button>

              <button
                type="button"
                onClick={() => setIsModelMenuOpen((prev) => !prev)}
                className="flex items-center gap-1.5 px-2 py-0.5 text-xs text-gray-300 hover:text-white hover:bg-[#1a1b1e] rounded-md transition-colors"
                title={`Model: ${selectedModel.displayName || selectedModel.name} (${selectedModel.providerDisplayName})`}
              >
                <span className="font-medium flex items-center gap-1">
                  {selectedModel.id === "auto" && <span className="text-amber-400 text-xs">✨</span>}
                  <span>{selectedModel.displayName || selectedModel.name}</span>
                </span>
                <ChevronUp size={11} className={`text-gray-400 transition-transform ${isModelMenuOpen ? "rotate-180" : ""}`} />
              </button>

              {/* Model Dropdown Menu */}
              {isModelMenuOpen && (
                <div className="absolute bottom-full left-0 mb-2 w-72 bg-[#0c0d0e] border border-[#1e1f22] rounded-xl shadow-2xl p-2 z-50 text-xs space-y-2 max-h-80 overflow-y-auto">
                  <div className="px-2 py-1 text-[10px] text-gray-400 font-bold uppercase tracking-wider border-b border-[#1e1f22]">
                    Select AI Model
                  </div>

                  {/* APInex Persistent Quota Summary */}
                  {apinexQuota && apinexQuota.configured && (
                    <div className="mx-1 my-1 p-2 rounded-lg bg-[#0c0d0e] border border-violet-900/40 text-gray-300">
                      <div className="flex items-center justify-between text-[11px] mb-1">
                        <span className="text-violet-300 font-medium">APInex daily usage:</span>
                        <span className="font-mono text-white font-semibold">
                          {apinexQuota.total_tokens.toLocaleString()} / {apinexQuota.daily_limit.toLocaleString()} tokens
                        </span>
                      </div>
                      <div className="w-full bg-[#0c0d0e] h-1.5 rounded-full overflow-hidden border border-violet-950">
                        <div
                          className={`h-full rounded-full transition-all duration-300 ${
                            apinexQuota.is_exhausted
                              ? "bg-red-500"
                              : apinexQuota.warning
                              ? "bg-amber-400"
                              : "bg-violet-500"
                          }`}
                          style={{ width: `${Math.min(100, apinexQuota.percent_used)}%` }}
                        />
                      </div>
                      <div className="flex items-center justify-between text-[9px] text-gray-400 mt-1">
                        <span>{apinexQuota.remaining_tokens.toLocaleString()} tokens remaining ({apinexQuota.percent_used}%)</span>
                        {apinexQuota.is_exhausted ? (
                          <span className="text-red-400 font-bold uppercase">Budget Exhausted</span>
                        ) : apinexQuota.warning ? (
                          <span className="text-amber-400 font-medium">≥80% Warning</span>
                        ) : (
                          <span className="text-emerald-400">Active</span>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="space-y-0.5">
                    {availableModels.map((model) => {
                      const isSelected = selectedModel.id === model.id && selectedModel.providerId === model.providerId;
                      const isAuto = model.id === "auto" || model.providerId === "auto";
                      return (
                        <button
                          key={`${model.providerId}:${model.id}`}
                          type="button"
                          onClick={() => {
                            setSelectedModel(model);
                            try {
                              localStorage.setItem("codebrain_selected_ai_provider", model.providerId);
                              localStorage.setItem("codebrain_selected_ai_model", model.id);
                            } catch {}

                            if (
                              model.providerId === "openai-compatible" ||
                              model.providerId === "anthropic-compatible" ||
                              model.providerId === "custom"
                            ) {
                              saveApiKeys({
                                preferred_ai_provider: model.providerId,
                                preferred_ai_model: model.id,
                              }).catch((err) => console.warn("Failed to set user custom model as primary:", err));
                            } else {
                              saveApiKeys({
                                preferred_ai_provider: "",
                                preferred_ai_model: "",
                              }).catch((err) => console.warn("Failed to clear custom provider override:", err));
                            }

                            setIsModelMenuOpen(false);
                          }}
                          className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left transition-colors ${
                            isSelected
                              ? "bg-purple-600 text-white"
                              : isAuto
                              ? "bg-purple-950/20 text-[#cccccc] hover:bg-[#1a1b1e] hover:text-white border-b border-[#1e1f22]/50 mb-1"
                              : "text-[#cccccc] hover:bg-[#1a1b1e] hover:text-white"
                          }`}
                        >
                          <div className="flex flex-col min-w-0 pr-2">
                            <span className="font-medium text-xs truncate flex items-center gap-1">
                              {isAuto && <span className="text-amber-400 text-xs">✨</span>}
                              <span>{model.displayName || model.name}</span>
                            </span>
                            <span className={`text-[10px] truncate ${isSelected ? "text-purple-100" : "text-gray-400"}`}>
                              {isAuto ? "Intelligent task-aware routing" : model.providerDisplayName}
                            </span>
                          </div>
                          <span
                            className={`text-[9px] px-1.5 py-0.5 rounded font-mono uppercase whitespace-nowrap shrink-0 ${
                              isSelected
                                ? "bg-purple-800 text-white"
                                : isAuto
                                ? "bg-[#0c0d0e] text-amber-300 border border-amber-900/40"
                                : "bg-[#0c0d0e] text-gray-300 border border-[#1e1f22]"
                            }`}
                          >
                            {model.badge}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-1.5">
              <VoiceMicButton onTranscribed={handleVoiceTranscribed} disabled={isStreaming} size="sm" />

              {isStreaming && (input.trim() || selectedImage) && (
                <button
                  id="queue-btn"
                  type="button"
                  onClick={handleQueueMessage}
                  className="px-2.5 py-1 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium flex items-center gap-1 transition-all shadow-sm"
                  title="Queue this message to run after current response finishes"
                >
                  <Clock size={12} />
                  <span>Queue</span>
                </button>
              )}

              {isStreaming ? (
                <button
                  id="stop-btn"
                  type="button"
                  onClick={handleStop}
                  className="w-7 h-7 rounded-full flex items-center justify-center bg-red-600 hover:bg-red-500 text-white transition-all shadow-md hover:scale-105 active:scale-95"
                  title="Stop generating"
                  aria-label="Stop generating"
                >
                  <Square size={10} className="fill-current text-white" />
                </button>
              ) : (
                <button
                  id="send-btn"
                  type="button"
                  onClick={() => handleSend()}
                  disabled={!input.trim() && !selectedImage}
                  className={`w-7 h-7 rounded-full flex items-center justify-center transition-all ${
                    input.trim() || selectedImage
                      ? "bg-purple-600 hover:bg-purple-500 text-white shadow-md shadow-purple-950/50 hover:scale-105 active:scale-95 cursor-pointer"
                      : "bg-[#141518] text-gray-500 cursor-not-allowed"
                  }`}
                  title="Send message"
                  aria-label="Send message"
                >
                  <ArrowRight size={14} className="text-white" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
