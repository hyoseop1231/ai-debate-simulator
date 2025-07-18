"""
최종 개선된 AI 토론 시뮬레이터
- 한국어 응답
- 자동 스크롤
- 모델 선택
- 토론 형식별 동적 UI
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import asyncio
import json
import uuid
from datetime import datetime
import random
import httpx
import os

from debate_agent import DebateAgent, AgentRole, DebateStance
from debate_controller import DebateController, DebateConfig, DebateFormat
from debate_evaluator import DebateEvaluator

app = FastAPI(title="AI 토론 시뮬레이터 Final", version="4.0")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 상태
active_debates = {}

# 환경 변수 설정
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")

# 토론 형식별 설정
DEBATE_FORMATS = {
    "adversarial": {
        "name": "대립형 토론 (MAD)",
        "support_team": "천사팀",
        "oppose_team": "악마팀",
        "organizer": {"name": "진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "희망천사", "role": "angel", "emoji": "😇"},
                {"name": "긍정작가", "role": "writer", "emoji": "✍️"}
            ],
            "oppose": [
                {"name": "도전악마", "role": "devil", "emoji": "😈"},
                {"name": "비판분석가", "role": "analyzer", "emoji": "🔍"}
            ]
        }
    },
    "collaborative": {
        "name": "협력형 토론",
        "support_team": "찬성 연구팀",
        "oppose_team": "반대 연구팀",
        "organizer": {"name": "연구진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "찬성연구원", "role": "searcher", "emoji": "🔎"},
                {"name": "찬성작가", "role": "writer", "emoji": "📝"}
            ],
            "oppose": [
                {"name": "반대연구원", "role": "searcher", "emoji": "🔍"},
                {"name": "반대작가", "role": "writer", "emoji": "✏️"}
            ]
        }
    },
    "competitive": {
        "name": "경쟁형 토론",
        "support_team": "블루팀",
        "oppose_team": "레드팀",
        "organizer": {"name": "심판", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "블루탐색자", "role": "searcher", "emoji": "🔵"},
                {"name": "블루전략가", "role": "writer", "emoji": "💙"}
            ],
            "oppose": [
                {"name": "레드탐색자", "role": "searcher", "emoji": "🔴"},
                {"name": "레드전략가", "role": "writer", "emoji": "❤️"}
            ]
        }
    },
    "custom": {
        "name": "커스텀 토론",
        "support_team": "커스텀 A팀",
        "oppose_team": "커스텀 B팀", 
        "organizer": {"name": "커스텀 진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [],  # 동적으로 생성
            "oppose": []    # 동적으로 생성
        },
        "custom": True
    }
}

class DebateSession:
    def __init__(self, session_id: str, config: DebateConfig):
        self.session_id = session_id
        self.config = config
        self.controller = None
        self.support_agents = []
        self.oppose_agents = []
        self.organizer = None  # 진행자 추가
        self.evaluator = DebateEvaluator()
        self.clients = []
        self.current_round = 0
        self.is_active = True

@app.get("/", response_class=HTMLResponse)
async def home():
    """메인 페이지"""
    return """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 토론 배틀 아레나</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            overflow: hidden;
        }
        
        /* 컨테이너 */
        .container {
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        /* 헤더 */
        .header {
            background: rgba(0,0,0,0.5);
            padding: 15px;
            text-align: center;
            border-bottom: 2px solid rgba(102, 126, 234, 0.3);
        }
        
        .header h1 {
            font-size: 2em;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        /* 메인 레이아웃 */
        .main-layout {
            flex: 1;
            display: grid;
            grid-template-columns: 300px 1fr 300px;
            height: calc(100vh - 80px);
            gap: 10px;
            padding: 10px;
        }
        
        /* 패널 스타일 */
        .panel {
            background: rgba(26, 26, 26, 0.9);
            border-radius: 10px;
            padding: 15px;
            overflow-y: auto;
            overflow-x: hidden;
        }
        
        .panel h2 {
            font-size: 1.2em;
            margin-bottom: 15px;
            color: #667eea;
        }
        
        /* 컨트롤 패널 */
        .control-panel {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        
        .form-group label {
            font-size: 0.9em;
            color: #aaa;
        }
        
        .form-group input,
        .form-group select,
        .form-group textarea {
            padding: 10px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(102, 126, 234, 0.3);
            border-radius: 5px;
            color: #fff;
            font-size: 14px;
        }
        
        .form-group textarea {
            resize: vertical;
            min-height: 60px;
        }
        
        /* 중앙 토론장 */
        .debate-arena {
            display: flex;
            flex-direction: column;
            position: relative;
        }
        
        .arena-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            margin-bottom: 10px;
        }
        
        .round-display {
            font-size: 1.2em;
            font-weight: bold;
            color: #FFD700;
        }
        
        .vs-indicator {
            font-size: 1.5em;
            color: #FFD700;
            text-shadow: 0 0 10px rgba(255, 215, 0, 0.5);
        }
        
        /* 대화 영역 */
        .chat-container {
            flex: 1;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 15px;
            overflow-y: auto;
            overflow-x: hidden;
            scroll-behavior: smooth;
            max-height: calc(100vh - 250px);
        }
        
        /* 대화 메시지 */
        .message {
            margin-bottom: 15px;
            /* animation 제거 - 깜빡거림 방지 */
        }
        
        .message.slide-in-left {
            /* animation 제거 - 깜빡거림 방지 */
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        @keyframes slideInLeft {
            from { 
                opacity: 0; 
                transform: translateX(-100px) scale(0.8); 
            }
            to { 
                opacity: 1; 
                transform: translateX(0) scale(1); 
            }
        }
        
        @keyframes textAppear {
            from { 
                opacity: 0; 
                transform: translateY(-5px) scale(0.9); 
            }
            to { 
                opacity: 1; 
                transform: translateY(0) scale(1); 
            }
        }
        
        .message.support {
            text-align: left;
        }
        
        .message.oppose {
            text-align: right;
        }
        
        .message.neutral {
            text-align: center;
        }
        
        .message-bubble {
            display: block;
            width: 85%;
            min-height: 60px;
            padding: 12px 16px;
            border-radius: 15px;
            position: relative;
            word-wrap: break-word;
            overflow-wrap: break-word;
            box-sizing: border-box;
        }
        
        .support .message-bubble {
            background: rgba(39, 174, 96, 0.15);
            border: 1px solid rgba(39, 174, 96, 0.3);
            color: #ffffff;
            margin-left: 0;
            margin-right: auto;
        }
        
        .oppose .message-bubble {
            background: rgba(231, 76, 60, 0.15);
            border: 1px solid rgba(231, 76, 60, 0.3);
            color: #ffffff;
            margin-left: auto;
            margin-right: 0;
        }
        
        .neutral .message-bubble {
            background: rgba(255, 215, 0, 0.15);
            border: 1px solid rgba(255, 215, 0, 0.3);
            color: #ffffff;
            margin-left: auto;
            margin-right: auto;
            width: 90%;
        }
        
        .message-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 5px;
            font-weight: bold;
        }
        
        .support .message-header {
            justify-content: flex-start;
        }
        
        .oppose .message-header {
            justify-content: flex-end;
            flex-direction: row-reverse;
        }
        
        .neutral .message-header {
            justify-content: center;
        }
        
        .agent-emoji {
            font-size: 1.5em;
        }
        
        .agent-pixel-avatar {
            width: 32px;
            height: 32px;
            image-rendering: pixelated;
            image-rendering: -moz-crisp-edges;
            image-rendering: crisp-edges;
            margin-right: 8px;
        }
        
        .agent-card .agent-pixel-avatar {
            width: 48px;
            height: 48px;
        }
        
        .agent-name {
            font-size: 0.9em;
        }
        
        .message-content {
            line-height: 1.5;
            font-size: 0.95em;
            direction: ltr;
            text-align: left;
            unicode-bidi: embed;
        }
        
        .quality-indicator {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 10px;
            font-size: 0.7em;
            margin-left: 10px;
            font-weight: bold;
        }
        
        .quality-high {
            background: rgba(39, 174, 96, 0.2);
            color: #27ae60;
        }
        
        .quality-medium {
            background: rgba(255, 193, 7, 0.2);
            color: #ffc107;
        }
        
        .quality-low {
            background: rgba(231, 76, 60, 0.2);
            color: #e74c3c;
        }
        
        /* 팀 패널 */
        .team-panel {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        
        .team-header {
            text-align: center;
            font-weight: bold;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 10px;
        }
        
        .support-team .team-header {
            background: rgba(39, 174, 96, 0.2);
            color: #27ae60;
        }
        
        .oppose-team .team-header {
            background: rgba(231, 76, 60, 0.2);
            color: #e74c3c;
        }
        
        .agent-card {
            background: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            /* transition 제거 - 깜빡거림 방지 */
        }
        
        .agent-card.speaking {
            transform: scale(1.05);
            background: rgba(255,255,255,0.1);
            box-shadow: 0 0 20px rgba(102, 126, 234, 0.5);
        }
        
        .agent-avatar {
            font-size: 3em;
            margin-bottom: 5px;
        }
        
        .agent-info {
            font-size: 0.9em;
        }
        
        /* 평가 영역 */
        .evaluation-section {
            margin-top: 20px;
            padding: 15px;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
        }
        
        .score-display {
            display: flex;
            justify-content: space-around;
            margin-bottom: 15px;
        }
        
        .score-item {
            text-align: center;
        }
        
        .score-label {
            font-size: 0.8em;
            color: #aaa;
        }
        
        .score-value {
            font-size: 2em;
            font-weight: bold;
            margin-top: 5px;
        }
        
        /* 버튼 스타일 */
        .btn {
            padding: 12px 20px;
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            /* transition 제거 - 깜빡거림 방지 */
            width: 100%;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        
        .btn-danger {
            background: linear-gradient(45deg, #e74c3c, #c0392b);
        }
        
        /* 상태 표시 */
        .status-bar {
            display: flex;
            gap: 15px;
            padding: 10px;
            background: rgba(0,0,0,0.3);
            border-radius: 5px;
            font-size: 0.9em;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 5px;
            margin-right: 20px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .status-bar {
            display: flex;
            flex-direction: column;
            gap: 5px;
            font-size: 0.85em;
        }
        
        @media (min-width: 768px) {
            .status-bar {
                flex-direction: row;
                gap: 15px;
            }
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #27ae60;
        }
        
        .status-dot.offline {
            background: #e74c3c;
        }
        
        /* 스크롤바 스타일 */
        ::-webkit-scrollbar {
            width: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb {
            background: rgba(102, 126, 234, 0.5);
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(102, 126, 234, 0.7);
        }
        
        /* KITECH 스타일 thinking 영역 */
        .thinking-section {
            background: rgba(128, 128, 128, 0.1);
            border: 1px solid rgba(128, 128, 128, 0.3);
            border-radius: 8px;
            margin-bottom: 10px;
            /* transition 제거 - 깜빡거림 방지 */
        }
        
        .thinking-header {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            background: rgba(128, 128, 128, 0.15);
            border-radius: 8px 8px 0 0;
            cursor: pointer;
            user-select: none;
        }
        
        .thinking-toggle {
            font-size: 0.8em;
            color: #888;
            /* transition 제거 - 깜빡거림 방지 */
        }
        
        .thinking-toggle.collapsed {
            transform: rotate(-90deg);
        }
        
        .thinking-content {
            padding: 12px;
            font-size: 0.85em;
            color: #999;
            line-height: 1.4;
            font-style: italic;
            max-height: 200px;
            overflow-y: auto;
            /* transition 제거 - 깜빡거림 방지 */
        }
        
        .thinking-content.collapsed {
            max-height: 0;
            padding: 0 12px;
            overflow: hidden;
        }
        
        /* KITECH 스타일 로딩 애니메이션 */
        .typing-indicator {
            display: flex;
            gap: 4px;
            padding: 10px;
            align-items: center;
            background: rgba(128, 128, 128, 0.1);
            border-radius: 8px;
            margin-bottom: 10px;
        }
        
        .typing-dot {
            width: 6px;
            height: 6px;
            background: #888;
            border-radius: 50%;
            /* animation 제거 - 깜빡거림 방지 */
        }
        
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        
        @keyframes typing {
            0%, 60%, 100% { transform: translateY(0); opacity: 0.3; }
            30% { transform: translateY(-8px); opacity: 0.8; }
        }
        
        /* 실시간 렌더링 애니메이션 */
        .text-cursor {
            display: inline-block;
            width: 2px;
            height: 1.2em;
            background: #667eea;
            /* animation 제거 - 깜빡거림 방지 */
            margin-left: 2px;
        }
        
        @keyframes blink {
            0%, 50% { opacity: 1; }
            51%, 100% { opacity: 0; }
        }
        
        /* 형식 변경 알림 애니메이션 */
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(100%); opacity: 0; }
        }
        
        /* 에이전트 카드 페이드인 애니메이션 강화 */
        @keyframes fadeIn {
            from { 
                opacity: 0; 
                transform: translateY(20px) scale(0.9); 
            }
            to { 
                opacity: 1; 
                transform: translateY(0) scale(1); 
            }
        }
        
        /* Thinking 메시지 스타일 */
        .thinking-message {
            margin-bottom: 10px;
        }
        
        .thinking-bubble {
            background: rgba(102, 126, 234, 0.1);
            border: 1px solid rgba(102, 126, 234, 0.3);
            border-radius: 10px;
            padding: 10px;
            margin-bottom: 10px;
            /* animation 제거 - 깜빡거림 방지 */
        }
        
        .thinking-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(102, 126, 234, 0.2);
        }
        
        .thinking-icon {
            font-size: 1.2em;
            margin-right: 8px;
        }
        
        .thinking-label {
            flex: 1;
            font-size: 0.9em;
            color: #a0a0ff;
            font-style: italic;
        }
        
        .thinking-toggle {
            cursor: pointer;
            font-size: 1.2em;
            color: #667eea;
            /* transition 제거 - 깜빡거림 방지 */
            user-select: none;
        }
        
        .thinking-toggle:hover {
            color: #764ba2;
        }
        
        .thinking-content {
            max-height: 0;
            overflow: hidden;
            /* transition 제거 - 깜빡거림 방지 */
            opacity: 0;
            transform: translateY(-10px);
            background: rgba(102, 126, 234, 0.05);
            border-radius: 0 0 8px 8px;
        }
        
        .thinking-content.expanded {
            max-height: 300px;
            opacity: 1;
            transform: translateY(0);
            padding: 12px;
            overflow-y: auto;
        }
        
        .thinking-text {
            font-size: 0.85em;
            color: #c0c0ff;
            line-height: 1.5;
            white-space: pre-wrap;
            padding: 5px 0;
            text-align: left;
            direction: ltr;
            unicode-bidi: embed;
        }
        
        .thinking-indicator {
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 10px;
            gap: 5px;
        }
        
        .thinking-indicator span {
            width: 8px;
            height: 8px;
            background: #667eea;
            border-radius: 50%;
            /* animation 제거 - 깜빡거림 방지 */
        }
        
        .thinking-indicator span:nth-child(2) {
            /* animation-delay 제거: 0.2s;
        }
        
        .thinking-indicator span:nth-child(3) {
            /* animation-delay 제거: 0.4s;
        }
        
        @keyframes thinking-pulse {
            0%, 60%, 100% {
                transform: scale(1);
                opacity: 0.5;
            }
            30% {
                transform: scale(1.3);
                opacity: 1;
            }
        }
        
        /* 에이전트 카드 thinking 상태 */
        .agent-card.thinking {
            background: rgba(102, 126, 234, 0.15);
            border: 1px solid rgba(102, 126, 234, 0.5);
            /* animation 제거 - 깜빡거림 방지 */
        }
        
        @keyframes thinking-glow {
            0%, 100% {
                box-shadow: 0 0 5px rgba(102, 126, 234, 0.3);
            }
            50% {
                box-shadow: 0 0 20px rgba(102, 126, 234, 0.6);
            }
        }
        
        /* 반응형 */
        @media (max-width: 1200px) {
            .main-layout {
                grid-template-columns: 250px 1fr 250px;
            }
        }
        
        @media (max-width: 768px) {
            .main-layout {
                grid-template-columns: 1fr;
                grid-template-rows: auto 1fr auto;
            }
            
            .team-panel {
                display: none;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚔️ AI 토론 배틀 아레나 ⚔️</h1>
        </div>
        
        <div class="main-layout">
            <!-- 왼쪽: 컨트롤 패널 -->
            <div class="panel control-panel">
                <h2>토론 설정</h2>
                
                <div class="form-group">
                    <label>토론 주제</label>
                    <textarea id="topic" placeholder="토론 주제를 입력하세요">인공지능이 인간의 일자리를 대체하는 것은 바람직한가?</textarea>
                </div>
                
                <div class="form-group">
                    <label>토론 형식</label>
                    <select id="format" onchange="updateDebateFormat()">
                        <option value="adversarial">대립형 (천사 vs 악마)</option>
                        <option value="collaborative">협력형 (연구팀)</option>
                        <option value="competitive">경쟁형 (팀 배틀)</option>
                        <option value="custom">커스텀 토론</option>
                    </select>
                </div>
                
                <!-- 커스텀 모드 설정 -->
                <div id="custom-settings" style="display: none;">
                    <div class="form-group">
                        <label>팀 당 멤버 수</label>
                        <input type="number" id="members-per-team" value="2" min="1" max="6" onchange="updateCustomAgentFields()">
                    </div>
                    
                    <div class="form-group">
                        <label>A팀 이름</label>
                        <input type="text" id="team-a-name" value="커스텀 A팀">
                    </div>
                    
                    <div class="form-group">
                        <label>B팀 이름</label>
                        <input type="text" id="team-b-name" value="커스텀 B팀">
                    </div>
                    
                    <div class="form-group">
                        <label>진행자 이름</label>
                        <input type="text" id="organizer-name" value="커스텀 진행자">
                    </div>
                    
                    <div class="form-group">
                        <label>토론 스타일</label>
                        <select id="custom-style" onchange="applyCustomPreset()">
                            <option value="custom">완전 커스텀</option>
                            <option value="academic">학술적 토론</option>
                            <option value="business">비즈니스 토론</option>
                            <option value="creative">창의적 토론</option>
                            <option value="scientific">과학적 토론</option>
                            <option value="philosophical">철학적 토론</option>
                        </select>
                    </div>
                    
                    <div id="custom-agents-config">
                        <!-- 동적으로 생성될 에이전트 설정 -->
                    </div>
                    
                    <button type="button" class="btn" onclick="generateCustomAgents()" style="margin-bottom: 15px;">
                        🎭 에이전트 구성 생성
                    </button>
                    
                    <button type="button" class="btn" onclick="previewPersonas()" style="margin-bottom: 15px; background: linear-gradient(45deg, #27ae60, #2ecc71);">
                        👁️ 페르소나 미리보기
                    </button>
                </div>
                
                <div class="form-group">
                    <label>AI 모델</label>
                    <select id="model">
                        <option value="">모델 로딩 중...</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label>라운드 수</label>
                    <input type="number" id="rounds" value="3" min="1" max="10">
                </div>
                
                <div class="form-group">
                    <label>응답 언어</label>
                    <select id="language">
                        <option value="ko">한국어</option>
                        <option value="en">English</option>
                    </select>
                </div>
                
                <button class="btn" onclick="if(typeof startDebate === 'function') startDebate()" id="startBtn">
                    🚀 토론 시작
                </button>
                
                <button class="btn btn-danger" onclick="if(typeof stopDebate === 'function') stopDebate()" id="stopBtn" disabled>
                    ⏹️ 토론 중지
                </button>
                
                <div class="status-bar">
                    <div class="status-item">
                        <span class="status-dot" id="status-dot"></span>
                        <span id="status-text">대기 중</span>
                    </div>
                    <div class="status-item">
                        <span>Ollama:</span>
                        <span id="ollama-status" style="max-width: 120px; overflow: hidden; text-overflow: ellipsis;">확인 중...</span>
                    </div>
                    <div class="status-item">
                        <span>모델:</span>
                        <span id="model-status" style="max-width: 150px; overflow: hidden; text-overflow: ellipsis;">확인 중...</span>
                    </div>
                </div>
            </div>
            
            <!-- 중앙: 토론장 -->
            <div class="panel debate-arena">
                <div class="arena-header">
                    <div class="round-display" id="round-display">토론 대기 중</div>
                    <div class="vs-indicator" id="vs-indicator">VS</div>
                    <div id="debate-timer">00:00</div>
                </div>
                
                <div class="chat-container" id="chat-container">
                    <div style="text-align: center; color: #666; margin-top: 50px;">
                        토론을 시작하려면 설정을 완료하고 '토론 시작' 버튼을 클릭하세요.
                    </div>
                </div>
            </div>
            
            <!-- 오른쪽: 팀 정보 및 평가 -->
            <div class="panel">
                <div id="team-display">
                    <!-- 동적으로 생성됨 -->
                </div>
                
                <div class="evaluation-section">
                    <h3 style="text-align: center; margin-bottom: 15px;">실시간 평가</h3>
                    <div class="score-display">
                        <div class="score-item">
                            <div class="score-label" id="support-label">지지팀</div>
                            <div class="score-value" style="color: #27ae60;" id="support-score">0.00</div>
                        </div>
                        <div class="score-item">
                            <div class="score-label" id="oppose-label">반대팀</div>
                            <div class="score-value" style="color: #e74c3c;" id="oppose-score">0.00</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let ws = null;
        let sessionId = null;
        let currentRound = 0;
        let maxRounds = 3;
        let debateActive = false;
        let debateStartTime = null;
        let timerInterval = null;
        let availableModels = [];
        let messageQueue = [];
        let isTyping = false;
        let roundInProgress = false;
        
        // Context7 연구 기반: 고급 thinking 태그 처리 시스템
        function processThinkingTags(text) {
            let cleanText = text;
            let thinkingContent = '';
            let hasThinking = false;
            let thinkingMetadata = {
                confidence: 0.5,
                reasoning_depth: 0,
                branch_count: 0,
                processing_time: Date.now()
            };
            
            // Context7 Generator-Critic 프레임워크 기반 패턴 매칭
            const patterns = [
                // XML 스타일 (우선순위 높음)
                { start: '<thinking>', end: '</thinking>', priority: 1, type: 'structured' },
                { start: '<thought>', end: '</thought>', priority: 2, type: 'casual' },
                { start: '<reasoning>', end: '</reasoning>', priority: 1, type: 'logical' },
                { start: '<analysis>', end: '</analysis>', priority: 1, type: 'analytical' },
                // 마크다운 스타일
                { start: '**thinking**', end: '**/thinking**', priority: 3, type: 'markdown' },
                { start: '**생각**', end: '**/생각**', priority: 3, type: 'korean' },
                { start: '**추론**', end: '**/추론**', priority: 2, type: 'inference' },
                // 콜론 스타일 (자연어)
                { start: '생각:', end: 'NEWLINE_BREAK', priority: 4, type: 'natural' },
                { start: '추론:', end: 'NEWLINE_BREAK', priority: 4, type: 'natural' },
                { start: '분석:', end: 'NEWLINE_BREAK', priority: 4, type: 'natural' },
                { start: '사고:', end: 'NEWLINE_BREAK', priority: 4, type: 'natural' },
                { start: '내부 생각:', end: 'NEWLINE_BREAK', priority: 4, type: 'internal' }
            ];
            
            // Context7 기반: 우선순위별 thinking 내용 추출
            const sortedPatterns = patterns.sort((a, b) => a.priority - b.priority);
            const extractedThoughts = [];
            
            for (let pattern of sortedPatterns) {
                let startPos = cleanText.indexOf(pattern.start);
                while (startPos !== -1) {
                    hasThinking = true;
                    let extractedContent = '';
                    
                    if (pattern.end === 'NEWLINE_BREAK') {
                        // 자연어 패턴: 다음 빈 줄까지 추출
                        let restText = cleanText.substring(startPos);
                        let doubleNewlinePos = restText.indexOf('\\n\\n');
                        if (doubleNewlinePos !== -1) {
                            extractedContent = restText.substring(pattern.start.length, doubleNewlinePos);
                            cleanText = cleanText.substring(0, startPos) + restText.substring(doubleNewlinePos + 4);
                        } else {
                            extractedContent = restText.substring(pattern.start.length);
                            cleanText = cleanText.substring(0, startPos);
                        }
                    } else {
                        // 구조화된 패턴: 태그 사이 내용 추출
                        let endPos = cleanText.indexOf(pattern.end, startPos + pattern.start.length);
                        if (endPos !== -1) {
                            extractedContent = cleanText.substring(startPos + pattern.start.length, endPos);
                            cleanText = cleanText.substring(0, startPos) + 
                                       cleanText.substring(endPos + pattern.end.length);
                        }
                    }
                    
                    if (extractedContent.trim()) {
                        extractedThoughts.push({
                            content: extractedContent.trim(),
                            type: pattern.type,
                            priority: pattern.priority,
                            timestamp: Date.now()
                        });
                        
                        // 메타데이터 업데이트
                        thinkingMetadata.reasoning_depth++;
                        if (pattern.type === 'logical' || pattern.type === 'analytical') {
                            thinkingMetadata.confidence += 0.1;
                        }
                    }
                    
                    // 다음 occurrence 검색
                    startPos = cleanText.indexOf(pattern.start, startPos);
                }
            }
            
            // 모든 thinking 내용을 우선순위 순으로 결합
            thinkingContent = extractedThoughts
                .sort((a, b) => a.priority - b.priority)
                .map(thought => `[${thought.type}] ${thought.content}`)
                .join('\\n\\n');
            
            return {
                content: cleanText.trim(),
                thinkingContent: thinkingContent,
                hasThinking: hasThinking,
                metadata: thinkingMetadata,
                thoughts: extractedThoughts
            };
        }
        
        // 간단한 마크다운 렌더러 (정규식 문제 해결)
        function renderMarkdown(text) {
            let result = text;
            
            // 볼드 텍스트 (**텍스트**)
            result = simpleReplace(result, '**', '</strong>', '<strong>');
            
            // 이탤릭 (*텍스트*)
            result = simpleReplace(result, '*', '</em>', '<em>');
            
            // 코드 블록 (`코드`)
            result = simpleReplace(result, '`', '</code>', '<code style="background: rgba(255,255,255,0.1); padding: 2px 4px; border-radius: 3px;">');
            
            // 줄바꿈
            result = result.split('\\n').join('<br>');
            
            return result;
        }
        
        // 간단한 문자열 대체 함수
        function simpleReplace(text, marker, endTag, startTag) {
            let result = text;
            let inTag = false;
            let parts = result.split(marker);
            
            if (parts.length > 1) {
                result = '';
                for (let i = 0; i < parts.length; i++) {
                    if (i === 0) {
                        result += parts[i];
                    } else {
                        if (inTag) {
                            result += endTag + parts[i];
                        } else {
                            result += startTag + parts[i];
                        }
                        inTag = !inTag;
                    }
                }
            }
            
            return result;
        }
        
        // KITECH 스타일 실시간 타이핑 애니메이션
        function typeText(element, text, speed = 25) {
            return new Promise((resolve) => {
                let index = 0;
                element.innerHTML = '';
                
                const timer = setInterval(() => {
                    if (index < text.length) {
                        const currentText = text.substring(0, index + 1);
                        // KITECH 스타일: 커서와 함께 실시간 렌더링
                        element.innerHTML = renderMarkdown(currentText) + '<span class="text-cursor"></span>';
                        index++;
                        
                        // 부드러운 자동 스크롤
                        const chatContainer = document.getElementById('chat-container');
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                    } else {
                        clearInterval(timer);
                        // 최종 렌더링 (커서 제거)
                        element.innerHTML = renderMarkdown(text);
                        resolve();
                    }
                }, speed);
            });
        }
        
        // 스트리밍 컨텐츠를 위한 즉시 업데이트 함수 (의도적 지연 효과)
        function typewriterText(element, text) {
            // 이전 컨텐츠와 비교
            const previousText = element.dataset.previousText || '';
            
            if (text !== previousText) {
                // 새로 추가된 부분만 찾기
                const newPart = text.substring(previousText.length);
                
                if (newPart) {
                    // 깜빡거림 완전 제거: 받은 청크를 바로 추가
                    element.textContent = text;
                }
                
                // 이전 컨텐츠 업데이트
                element.dataset.previousText = text;
            }
        }
        
        // KITECH 스타일 thinking 섹션 생성
        function createThinkingSection(thinkingContent) {
            const thinkingId = 'thinking-' + Date.now();
            return `
                <div class="thinking-section" id="${thinkingId}">
                    <div class="thinking-header" onclick="toggleThinking('${thinkingId}')">
                        <span class="thinking-toggle">▼</span>
                        <span style="color: #888; font-size: 0.8em;">🧠 AI 사고 과정</span>
                    </div>
                    <div class="thinking-content" id="${thinkingId}-content">
                        ${renderMarkdown(thinkingContent)}
                    </div>
                </div>
            `;
        }
        
        // thinking 접기/펼치기
        function toggleThinking(thinkingId) {
            const content = document.getElementById(thinkingId + '-content');
            const toggle = document.querySelector(`#${thinkingId} .thinking-toggle`);
            
            if (content.classList.contains('collapsed')) {
                content.classList.remove('collapsed');
                toggle.classList.remove('collapsed');
                toggle.textContent = '▼';
            } else {
                content.classList.add('collapsed');
                toggle.classList.add('collapsed');
                toggle.textContent = '▶';
            }
        }
        
        // 메시지 큐 처리
        async function processMessageQueue() {
            if (isTyping || messageQueue.length === 0) return;
            
            isTyping = true;
            const argument = messageQueue.shift();
            await displayArgument(argument);
            isTyping = false;
            
            // 다음 메시지 처리
            if (messageQueue.length > 0) {
                setTimeout(() => processMessageQueue(), 500); // 500ms 딜레이
            }
        }
        
        // 메시지를 큐에 추가
        function addToMessageQueue(argument) {
            messageQueue.push(argument);
            processMessageQueue();
        }
        
        // Ollama 서버 상태 확인
        async function checkOllamaStatus() {
            const ollamaStatus = document.getElementById('ollama-status');
            
            try {
                const response = await fetch('/api/ollama/status');
                const data = await response.json();
                
                if (data.success && data.status === 'online') {
                    ollamaStatus.textContent = '✅ 연결됨';
                    ollamaStatus.style.color = '#27ae60';
                    return true;
                } else {
                    throw new Error(data.error || 'Ollama 서버 오프라인');
                }
            } catch (error) {
                console.error('Ollama 연결 실패:', error);
                ollamaStatus.textContent = '❌ 연결 실패';
                ollamaStatus.style.color = '#e74c3c';
                return false;
            }
        }
        
        // 페이지 로드 시
        document.addEventListener('DOMContentLoaded', function() {
            console.log('페이지 로드 완료, 초기화 시작...');
            
            // 즉시 UI 업데이트
            updateDebateFormat();
            checkStatus();
            setInterval(checkStatus, 5000);
            
            // 비동기 작업들을 별도로 실행
            setTimeout(async function() {
                try {
                    console.log('Ollama 상태 확인 시작...');
                    await checkOllamaStatus();
                    
                    console.log('모델 로드 시작...');
                    await loadAvailableModels();
                    
                    console.log('모든 초기화 완료');
                } catch (error) {
                    console.error('초기화 오류:', error);
                }
            }, 100);
        });
        
        // 사용 가능한 모델 로드
        async function loadAvailableModels() {
            const modelSelect = document.getElementById('model');
            const modelStatus = document.getElementById('model-status');
            
            if (!modelSelect || !modelStatus) {
                console.error('모델 관련 UI 요소를 찾을 수 없습니다');
                return;
            }
            
            console.log('모델 로드 시작...');
            modelStatus.textContent = '모델 확인 중...';
            modelStatus.style.color = '#666';
            
            try {
                console.log('API 요청 전송: /api/models');
                const response = await fetch('/api/models', {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                });
                
                console.log('응답 상태:', response.status, response.statusText);
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                console.log('응답 데이터:', data);
                
                if (data.success && data.models && Array.isArray(data.models) && data.models.length > 0) {
                    availableModels = data.models;
                    
                    // 기존 옵션 초기화
                    modelSelect.innerHTML = '';
                    
                    // 모델 옵션 추가 (qwen3:30b-a3b 우선)
                    data.models.forEach((model, index) => {
                        const option = document.createElement('option');
                        option.value = model.name;
                        option.textContent = `${model.name} (${model.size})`;
                        
                        // qwen3:30b-a3b를 기본으로 선택
                        if (model.name === 'qwen3:30b-a3b') {
                            option.selected = true;
                        } else if (index === 0 && !data.models.some(m => m.name === 'qwen3:30b-a3b')) {
                            option.selected = true;
                        }
                        
                        modelSelect.appendChild(option);
                        console.log(`모델 추가됨: ${model.name} (${model.size})`);
                    });
                    
                    modelStatus.textContent = `✅ ${data.models.length}개 모델 사용 가능`;
                    modelStatus.style.color = '#27ae60';
                    console.log(`총 ${data.models.length}개 모델 로드 완료`);
                } else {
                    throw new Error(`잘못된 응답 형식: ${JSON.stringify(data)}`);
                }
            } catch (error) {
                console.error('모델 로드 실패:', error);
                modelStatus.textContent = '❌ 모델 로드 실패';
                modelStatus.style.color = '#e74c3c';
                
                // 폴백: 기본 모델 추가
                modelSelect.innerHTML = '';
                const fallbackOption = document.createElement('option');
                fallbackOption.value = 'qwen3:30b-a3b';
                fallbackOption.textContent = 'qwen3:30b-a3b (기본)';
                modelSelect.appendChild(fallbackOption);
                console.log('폴백 모델 추가됨');
            }
        }
        
        // 상태 체크
        async function checkStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                updateStatus('온라인', true);
            } catch (error) {
                updateStatus('오프라인', false);
            }
        }
        
        // 토론 형식 업데이트 (향상된 커스텀 모드 지원)
        function updateDebateFormat() {
            const format = document.getElementById('format').value;
            const customSettings = document.getElementById('custom-settings');
            
            // 토론 형식 변경 시 자동 모드/사용자 업데이트
            if (format === 'custom') {
                customSettings.style.display = 'block';
                updateCustomAgentFields();
                return;
            } else {
                customSettings.style.display = 'none';
                // 기존 형식으로 자동 변경 시 모드와 사용자 즉시 업데이트
                autoUpdateModeAndUsers(format);
            }
            
            const formatData = JSON.parse('""" + json.dumps(DEBATE_FORMATS, ensure_ascii=False).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"') + """');
            const selected = formatData[format];
            
            updateTeamDisplay(selected);
            
            // 라벨 업데이트
            document.getElementById('support-label').textContent = selected.support_team;
            document.getElementById('oppose-label').textContent = selected.oppose_team;
            
            // 형식 변경 시 아바타 재생성
            if (!debateActive) {
                setTimeout(() => {
                    initializeAvatars();
                }, 100);
            }
        }
        
        // 팀 디스플레이 업데이트 (재사용 가능한 함수)
        function updateTeamDisplay(formatConfig) {
            const teamDisplay = document.getElementById('team-display');
            teamDisplay.innerHTML = `
                <div class="team-panel support-team">
                    <div class="team-header">${formatConfig.support_team}</div>
                    ${formatConfig.agents.support.map(agent => `
                        <div class="agent-card" id="${agent.name}-card">
                            <div class="agent-avatar">${agent.emoji}</div>
                            <div class="agent-info">${agent.name}</div>
                        </div>
                    `).join('')}
                </div>
                <div class="team-panel oppose-team" style="margin-top: 20px;">
                    <div class="team-header">${formatConfig.oppose_team}</div>
                    ${formatConfig.agents.oppose.map(agent => `
                        <div class="agent-card" id="${agent.name}-card">
                            <div class="agent-avatar">${agent.emoji}</div>
                            <div class="agent-info">${agent.name}</div>
                        </div>
                    `).join('')}
                </div>
            `;
        }
        
        // 토론 시작 (커스텀 모드 지원 강화)
        async function startDebate() {
            const topic = document.getElementById('topic').value;
            const format = document.getElementById('format').value;
            const model = document.getElementById('model').value;
            const language = document.getElementById('language').value;
            maxRounds = parseInt(document.getElementById('rounds').value);
            
            if (!topic) {
                alert('토론 주제를 입력하세요!');
                return;
            }
            
            // 커스텀 모드 검증
            let supportAgents, opposeAgents, customConfig = null;
            if (format === 'custom') {
                if (!window.customAgentsConfig) {
                    alert('커스텀 에이전트를 먼저 생성하세요!');
                    return;
                }
                supportAgents = window.customAgentsConfig.support;
                opposeAgents = window.customAgentsConfig.oppose;
                customConfig = window.customAgentsConfig;
            } else {
                const formatData = JSON.parse('""" + json.dumps(DEBATE_FORMATS, ensure_ascii=False).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"') + """');
                const selected = formatData[format];
                supportAgents = selected.agents.support;
                opposeAgents = selected.agents.oppose;
            }
            
            // 상태 초기화
            currentRound = 0;
            roundInProgress = false;
            messageQueue = [];
            isTyping = false;
            
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
            document.getElementById('chat-container').innerHTML = '';
            
            // 타이머 시작
            debateStartTime = Date.now();
            startTimer();
            
            try {
                const response = await fetch('/api/debate/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        topic: topic,
                        format: format,
                        max_rounds: maxRounds,
                        model: model,
                        language: language,
                        support_agents: supportAgents,
                        oppose_agents: opposeAgents,
                        custom_config: customConfig
                    })
                });
                
                const data = await response.json();
                sessionId = data.session_id;
                
                connectWebSocket();
                
                debateActive = true;
                currentRound = 0;
                
                // 픽셀아트 아바타 초기화
                addSystemMessage('AI 에이전트 아바타를 생성하는 중...');
                setTimeout(() => {
                    initializeAvatars();
                    addSystemMessage('토론이 시작되었습니다!');
                }, 500);
                
            } catch (error) {
                console.error('Error:', error);
                alert('토론 시작 중 오류가 발생했습니다.');
                document.getElementById('startBtn').disabled = false;
                document.getElementById('stopBtn').disabled = true;
            }
        }
        
        // WebSocket 연결
        function connectWebSocket() {
            ws = new WebSocket(`ws://localhost:8003/ws/${sessionId}`);
            
            ws.onopen = () => {
                console.log('WebSocket 연결됨');
                updateStatus('연결됨', true);
            };
            
            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    handleWebSocketMessage(data);
                } catch (error) {
                    console.error('WebSocket 메시지 파싱 오류:', error);
                }
            };
            
            ws.onclose = () => {
                console.log('WebSocket 연결 종료');
                updateStatus('연결 끊김', false);
            };
        }
        
        // Context7 기반: 강화된 WebSocket 메시지 처리
        function handleWebSocketMessage(data) {
            const messageTime = Date.now();
            const messageType = data.type;
            
            // 타임스탬프 경고 비활성화 (시스템 시간 동기화 문제)
            // if (data.metadata && data.metadata.timestamp) {
            //     const serverTime = data.metadata.timestamp;
            //     const latency = messageTime - serverTime;
            //     if (latency > 1000) {
            //         console.warn(`⚠️ 높은 지연시간: ${latency}ms for ${messageType}`);
            //     }
            // }
            
            // 디버깅용 로그
            console.log(`📨 메시지 수신: ${messageType}`, data);
            
            // Context7 기반: 메시지 타입별 처리
            switch(messageType) {
                case 'connection_confirmed':
                    handleConnectionConfirmed(data.data);
                    break;
                    
                case 'heartbeat':
                    handleHeartbeat(data.data);
                    break;
                    
                case 'sync_response':
                    handleSyncResponse(data.data);
                    break;
                    
                case 'round_start':
                    onRoundStart(data.data);
                    break;
                    
                case 'argument':
                    addToMessageQueue(data.data);
                    break;
                    
                case 'typing':
                    showTypingIndicator(data.data);
                    break;
                    
                case 'evaluation':
                    updateScores(data.data);
                    break;
                    
                case 'round_complete':
                    onRoundComplete(data.data);
                    break;
                    
                case 'debate_complete':
                    onDebateComplete(data.data);
                    break;
                    
                // 스트리밍 관련 메시지 타입들
                case 'thinking_start':
                    onThinkingStart(data.data);
                    break;
                    
                case 'thinking_chunk':
                    onThinkingChunk(data.data);
                    break;
                    
                case 'thinking_complete':
                    onThinkingComplete(data.data);
                    break;
                    
                case 'content_chunk':
                    onContentChunk(data.data);
                    break;
                    
                case 'argument_complete':
                    onArgumentComplete(data.data);
                    break;
                    
                case 'system':
                    onSystemMessage(data.data);
                    break;
                    
                default:
                    console.log(`🔍 알 수 없는 메시지 타입: ${messageType}`, data);
            }
        }
        
        // Context7 기반: 연결 확인 처리
        function handleConnectionConfirmed(data) {
            console.log(`✅ 연결 확인됨: ${data.client_id}`);
            window.clientId = data.client_id;
            window.serverTime = data.server_time;
            
            // 클라이언트-서버 시간 동기화
            const clientTime = Date.now();
            window.timeOffset = data.server_time - clientTime;
            console.log(`🕒 시간 오프셋: ${window.timeOffset}ms`);
        }
        
        // 하트비트 처리
        function handleHeartbeat(data) {
            // 자동 응답
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'ping',
                    data: {
                        client_id: window.clientId,
                        timestamp: Date.now()
                    }
                }));
            }
        }
        
        // 동기화 응답 처리
        function handleSyncResponse(data) {
            console.log('🔄 상태 동기화 수신:', data);
            
            // 서버 상태와 클라이언트 상태 비교
            if (data.current_round !== currentRound) {
                console.log(`🔄 라운드 동기화: ${currentRound} → ${data.current_round}`);
                currentRound = data.current_round;
                document.getElementById('round-display').textContent = `라운드 ${currentRound} / ${maxRounds}`;
            }
        }
        
        // Context7 연구 기반: 고급 라운드 동기화 시스템
        function onRoundStart(data) {
            const roundStartTime = Date.now();
            console.log(`🔄 라운드 시작 요청: ${data.round}, 현재: ${currentRound}, 진행중: ${roundInProgress}, 시간: ${roundStartTime}`);
            
            // Context7 기반: 원자적 상태 검증
            const stateSnapshot = {
                currentRound: currentRound,
                roundInProgress: roundInProgress,
                messageQueueLength: messageQueue.length,
                isTyping: isTyping,
                timestamp: roundStartTime
            };
            
            // 고급 중복 방지 및 상태 검증
            if (data.round === currentRound && roundInProgress) {
                console.log(`⚠️ 라운드 ${data.round} 중복 시작 방지 - 상태:`, stateSnapshot);
                
                // 상태 동기화 확인 요청
                requestStateSynchronization(data.round);
                return;
            }
            
            // Context7 기반: 강화된 순서 검증
            const isValidTransition = validateRoundTransition(currentRound, data.round);
            if (!isValidTransition.valid) {
                console.log(`❌ 잘못된 라운드 전환: ${isValidTransition.reason}`);
                handleRoundSyncError(data, stateSnapshot);
                return;
            }
            
            // 원자적 상태 업데이트 (Context7 패턴)
            const updateSuccess = atomicRoundUpdate(data.round, stateSnapshot);
            if (!updateSuccess) {
                console.log(`❌ 라운드 ${data.round} 상태 업데이트 실패`);
                return;
            }
            
            // UI 업데이트 (배치 처리)
            batchUIUpdate({
                roundDisplay: `라운드 ${currentRound} / ${maxRounds}`,
                systemMessage: `🔔 **라운드 ${currentRound}** 시작! (최대 ${maxRounds}라운드)`,
                roundProgress: (currentRound / maxRounds) * 100
            });
            
            console.log(`✅ 라운드 ${currentRound} 정상 시작 - 소요시간: ${Date.now() - roundStartTime}ms`);
        }
        
        // Context7 기반: 라운드 전환 검증
        function validateRoundTransition(currentRound, requestedRound) {
            if (requestedRound === currentRound + 1) {
                return { valid: true, reason: 'sequential_progression' };
            }
            if (currentRound === 0 && requestedRound === 1) {
                return { valid: true, reason: 'initial_round' };
            }
            if (requestedRound === currentRound) {
                return { valid: false, reason: 'duplicate_round' };
            }
            if (requestedRound < currentRound) {
                return { valid: false, reason: 'backward_progression' };
            }
            return { valid: false, reason: 'invalid_jump' };
        }
        
        // Context7 기반: 원자적 라운드 업데이트
        function atomicRoundUpdate(newRound, previousState) {
            try {
                // 상태 백업
                const backup = {
                    currentRound: currentRound,
                    roundInProgress: roundInProgress,
                    messageQueue: [...messageQueue],
                    isTyping: isTyping
                };
                
                // 원자적 업데이트
                currentRound = newRound;
                roundInProgress = true;
                messageQueue = [];
                isTyping = false;
                
                // 상태 검증
                if (currentRound !== newRound) {
                    throw new Error('State update verification failed');
                }
                
                return true;
            } catch (error) {
                console.error('원자적 라운드 업데이트 실패:', error);
                
                // 롤백
                currentRound = backup.currentRound;
                roundInProgress = backup.roundInProgress;
                messageQueue = backup.messageQueue;
                isTyping = backup.isTyping;
                
                return false;
            }
        }
        
        // Context7 기반: 배치 UI 업데이트
        function batchUIUpdate(updates) {
            requestAnimationFrame(() => {
                if (updates.roundDisplay) {
                    document.getElementById('round-display').textContent = updates.roundDisplay;
                }
                if (updates.systemMessage) {
                    addSystemMessage(updates.systemMessage);
                }
                if (updates.roundProgress) {
                    updateRoundProgress(updates.roundProgress);
                }
            });
        }
        
        // 라운드 진행률 업데이트
        function updateRoundProgress(progress) {
            const vsIndicator = document.getElementById('vs-indicator');
            if (vsIndicator) {
                // 진행률에 따른 시각적 효과
                const intensity = Math.min(progress / 100, 1);
                vsIndicator.style.opacity = 0.7 + (intensity * 0.3);
                vsIndicator.style.transform = `scale(${0.9 + intensity * 0.1})`;
            }
        }
        
        // 상태 동기화 요청
        function requestStateSynchronization(round) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'sync_request',
                    data: {
                        round: round,
                        clientState: {
                            currentRound: currentRound,
                            roundInProgress: roundInProgress,
                            timestamp: Date.now()
                        }
                    }
                }));
            }
        }
        
        // 라운드 동기화 오류 처리
        function handleRoundSyncError(data, stateSnapshot) {
            console.warn('라운드 동기화 오류 - 복구 시도:', { data, stateSnapshot });
            
            // 복구 전략
            setTimeout(() => {
                requestStateSynchronization(data.round);
            }, 1000);
        }
        
        // 논증 표시 (스트리밍 효과 포함)
        async function displayArgument(argument) {
            hideTypingIndicator();
            
            const chatContainer = document.getElementById('chat-container');
            const isSupport = argument.stance === 'support';
            
            // 에이전트 카드 하이라이트
            const agentCard = document.getElementById(`${argument.agent_name}-card`);
            if (agentCard) {
                agentCard.classList.add('speaking');
                setTimeout(() => agentCard.classList.remove('speaking'), 3000);
            }
            
            const message = document.createElement('div');
            message.className = `message ${argument.stance}`;
            
            const formatData = JSON.parse('""" + json.dumps(DEBATE_FORMATS, ensure_ascii=False).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"') + """');
            const format = document.getElementById('format').value;
            const agents = formatData[format].agents;
            const allAgents = [...agents.support, ...agents.oppose];
            const agent = allAgents.find(a => a.name === argument.agent_name) || {emoji: '🤖'};
            
            // KITECH 스타일 thinking 태그 처리
            const processed = processThinkingTags(argument.content);
            
            // 품질 점수 계산 (KITECH 방식)
            const qualityScore = argument.quality_score || 0.7;
            let qualityClass = 'quality-medium';
            let qualityText = '보통';
            
            if (qualityScore >= 0.8) {
                qualityClass = 'quality-high';
                qualityText = '우수';
            } else if (qualityScore < 0.6) {
                qualityClass = 'quality-low';
                qualityText = '개선 필요';
            }
            
            // KITECH 스타일 메시지 구성
            let messageHTML = `
                <div class="message-bubble">
                    <div class="message-header">
                        <span class="agent-emoji">${agent.emoji}</span>
                        <span class="agent-name">${argument.agent_name}</span>
                        <span class="quality-indicator ${qualityClass}">품질: ${qualityText}</span>
                    </div>
            `;
            
            // thinking 섹션 추가 (KITECH 스타일)
            if (processed.hasThinking && processed.thinkingContent) {
                messageHTML += createThinkingSection(processed.thinkingContent);
            }
            
            messageHTML += `
                    <div class="message-content"></div>
                </div>
            `;
            
            message.innerHTML = messageHTML;
            
            chatContainer.appendChild(message);
            
            // 스트리밍 효과로 텍스트 표시
            const messageContent = message.querySelector('.message-content');
            await typeText(messageContent, processed.content, 25);
            
            // thinking 표시 제거
            const thinkingIndicator = message.querySelector('.thinking-indicator');
            if (thinkingIndicator) {
                thinkingIndicator.remove();
            }
        }
        
        // 타이핑 표시
        function showTypingIndicator(data) {
            hideTypingIndicator();
            
            const chatContainer = document.getElementById('chat-container');
            const indicator = document.createElement('div');
            indicator.id = 'typing-indicator';
            indicator.className = 'message ' + data.stance;
            indicator.innerHTML = `
                <div class="typing-indicator">
                    <span>${data.agent_name}가 입력 중</span>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            `;
            
            chatContainer.appendChild(indicator);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        function hideTypingIndicator() {
            const indicator = document.getElementById('typing-indicator');
            if (indicator) indicator.remove();
        }
        
        // 점수 업데이트
        function updateScores(scores) {
            animateScore('support-score', scores.support_team || 0);
            animateScore('oppose-score', scores.oppose_team || 0);
        }
        
        // 점수 애니메이션
        function animateScore(elementId, targetScore) {
            const element = document.getElementById(elementId);
            const currentScore = parseFloat(element.textContent);
            const steps = 20;
            const increment = (targetScore - currentScore) / steps;
            let step = 0;
            
            // 애니메이션 제거 - 바로 점수 업데이트
            element.textContent = targetScore.toFixed(2);
        }
        
        // 라운드 완료
        function onRoundComplete(data) {
            console.log(`라운드 ${data.round} 완료 요청`);
            
            // 메시지 큐가 비워진 후에 라운드 완료 처리
            const checkQueueAndComplete = () => {
                if (messageQueue.length === 0 && !isTyping) {
                    if (data.round === currentRound && roundInProgress) {
                        roundInProgress = false;
                        addSystemMessage(`✅ 라운드 ${data.round} 완료`);
                        console.log(`라운드 ${data.round} 정상 완료`);
                    }
                } else {
                    setTimeout(checkQueueAndComplete, 200);
                }
            };
            
            // 약간의 딜레이 후 완료 처리 (메시지 타이핑 완료 대기)
            setTimeout(checkQueueAndComplete, 500);
        }
        
        // 토론 완료
        function onDebateComplete(data) {
            debateActive = false;
            roundInProgress = false;
            stopTimer();
            
            const winner = data.winner === 'support' ? 
                document.getElementById('support-label').textContent : 
                document.getElementById('oppose-label').textContent;
            
            addSystemMessage(`🏆 토론 종료! 승자: ${winner}`);
            addSystemMessage(`최종 점수: ${data.support_score.toFixed(2)} vs ${data.oppose_score.toFixed(2)}`);
            
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
        }
        
        // 토론 중지
        function stopDebate() {
            if (ws) ws.close();
            debateActive = false;
            stopTimer();
            
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            
            addSystemMessage('토론이 중지되었습니다.');
        }
        
        // === 스트리밍 관련 핸들러 함수들 ===
        
        // 현재 스트리밍 중인 메시지들을 추적
        const streamingMessages = new Map();
        
        // Thinking 시작
        function onThinkingStart(data) {
            hideTypingIndicator();
            
            const chatContainer = document.getElementById('chat-container');
            const round = data.round || currentRound;
            const messageId = `${data.agent_name}-${round}-thinking`;
            
            // 이미 존재하는지 확인 (중복 방지) - 더 엄격하게 처리
            if (document.getElementById(messageId) || streamingMessages.has(messageId)) {
                console.log(`🔄 Thinking 메시지 이미 존재: ${messageId}`);
                return;
            }
            
            // 에이전트 카드 하이라이트
            const agentCard = document.getElementById(`${data.agent_name}-card`);
            if (agentCard) {
                agentCard.classList.add('thinking');
            }
            
            // 픽셀 아바타 가져오기
            const avatarUrl = getAgentAvatar(data.agent_name);
            const avatarHtml = avatarUrl ? 
                `<img src="${avatarUrl}" alt="${data.agent_name}" class="agent-pixel-avatar">` : 
                `<span class="thinking-icon">🧠</span>`;
            
            // Thinking 컨테이너 생성
            const thinkingDiv = document.createElement('div');
            thinkingDiv.id = messageId;
            thinkingDiv.className = `message ${data.stance || 'neutral'} thinking-message`;
            thinkingDiv.innerHTML = `
                <div class="thinking-bubble">
                    <div class="thinking-header">
                        ${avatarHtml}
                        <span class="thinking-label">${data.agent_name}의 사고 과정...</span>
                        <span class="thinking-toggle" onclick="toggleThinking('${messageId}')" style="transform: rotate(0deg);">▼</span>
                    </div>
                    <div class="thinking-content expanded" id="${messageId}-content">
                        <div class="thinking-text"></div>
                        <div class="thinking-indicator">
                            <span></span><span></span><span></span>
                        </div>
                    </div>
                </div>
            `;
            
            chatContainer.appendChild(thinkingDiv);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            
            // 스트리밍 상태 저장
            streamingMessages.set(messageId, {
                element: thinkingDiv,
                content: '',
                type: 'thinking',
                round: round
            });
        }
        
        // Thinking 청크 추가
        function onThinkingChunk(data) {
            // 현재 활성화된 thinking 메시지 찾기
            let messageId = null;
            let streaming = null;
            
            // streamingMessages에서 해당 에이전트의 thinking 메시지 찾기
            for (const [key, value] of streamingMessages) {
                if (key.startsWith(`${data.agent_name}-`) && key.endsWith('-thinking') && value.type === 'thinking') {
                    messageId = key;
                    streaming = value;
                    break;
                }
            }
            
            if (streaming) {
                streaming.content += data.chunk;
                const textElement = streaming.element.querySelector('.thinking-text');
                if (textElement) {
                    // 깜빡거리는 효과 없이 부드럽게 글자 단위 스트리밍
                    textElement.style.textAlign = 'left';
                    textElement.style.direction = 'ltr';
                    
                    // 깜빡거림 완전 제거: 받은 청크를 바로 표시
                    textElement.textContent = streaming.content;
                    
                    // 스크롤 조정
                    const chatContainer = document.getElementById('chat-container');
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
            } else {
                // thinking 컨테이너가 없는 경우 (비추론 모델 등) 자동으로 생성
                console.log(`⚠️ Thinking 메시지를 찾을 수 없음: ${data.agent_name} - 자동 생성 시도`);
                
                // thinking_start 이벤트를 강제로 호출하여 컨테이너 생성
                const round = data.round || currentRound;
                onThinkingStart({
                    agent_name: data.agent_name,
                    stance: data.stance || 'neutral',
                    round: round
                });
                
                // 다시 시도
                setTimeout(() => {
                    onThinkingChunk(data);
                }, 100);
            }
        }
        
        // Thinking 완료
        function onThinkingComplete(data) {
            // 현재 활성화된 thinking 메시지 찾기
            let messageId = null;
            let streaming = null;
            
            // streamingMessages에서 해당 에이전트의 thinking 메시지 찾기
            for (const [key, value] of streamingMessages) {
                if (key.startsWith(`${data.agent_name}-`) && key.endsWith('-thinking') && value.type === 'thinking') {
                    messageId = key;
                    streaming = value;
                    break;
                }
            }
            
            if (streaming) {
                // Thinking 인디케이터 제거
                const indicator = streaming.element.querySelector('.thinking-indicator');
                if (indicator) {
                    indicator.remove();
                }
                
                // 에이전트 카드에서 thinking 클래스 제거
                const agentCard = document.getElementById(`${data.agent_name}-card`);
                if (agentCard) {
                    agentCard.classList.remove('thinking');
                    agentCard.classList.add('speaking');
                }
                
                // Thinking 완료 후 3초 후 자동 접기
                const thinkingContent = document.getElementById(`${messageId}-content`);
                const toggle = document.querySelector(`#${messageId} .thinking-toggle`);
                
                if (thinkingContent && toggle) {
                    // 이미 펼쳐진 상태이므로 잠시 완료 표시만 하고 접기
                    // 헤더 텍스트 변경
                    const label = streaming.element.querySelector('.thinking-label');
                    if (label) {
                        label.textContent = `${data.agent_name}의 사고 과정 (완료)`;
                    }
                    
                    // 3초 후 자동 접기
                    setTimeout(() => {
                        thinkingContent.classList.remove('expanded');
                        toggle.textContent = '▶';
                        toggle.style.transform = 'rotate(-90deg)';
                    }, 3000);
                }
                
                streamingMessages.delete(messageId);
            } else {
                // thinking 컨테이너가 없는 경우 (비추론 모델 등) 무시
                console.log(`⚠️ Thinking 완료 메시지를 처리할 컨테이너가 없음: ${data.agent_name}`);
            }
        }
        
        // Content 청크 추가 (실제 응답) - 백엔드에서 thinking 처리됨
        function onContentChunk(data) {
            const messageId = `${data.agent_name}-${currentRound}-content`;
            let streaming = streamingMessages.get(messageId);
            
            // thinking 태그가 포함된 청크는 완전히 무시 (백엔드에서 처리됨)
            const chunk = data.chunk;
            
            // thinking 태그가 명확히 포함된 청크만 무시
            const thinkingTagPatterns = [
                '<thinking>', '</thinking>',
                '<think>', '</think>'
            ];
            
            // thinking 태그가 명확히 포함된 경우만 무시
            if (thinkingTagPatterns.some(pattern => chunk.includes(pattern))) {
                console.log('🚫 thinking 태그 청크 무시:', chunk.substring(0, 50) + '...');
                return;
            }
            
            // thinking 태그의 시작 부분이 포함된 경우도 무시
            const partialThinkingPatterns = ['<thi', '<thin', '<think', '<thinki', '<thinkin', '<thinking'];
            if (partialThinkingPatterns.some(pattern => chunk.endsWith(pattern))) {
                console.log('🚫 부분적 thinking 태그 무시:', chunk);
                return;
            }
            
            // 빈 청크나 공백만 있는 청크 무시
            if (!chunk || chunk.trim() === '') {
                return;
            }
            
            if (!streaming) {
                // 첫 번째 content chunk일 때 메시지 컨테이너 생성
                const chatContainer = document.getElementById('chat-container');
                const messageDiv = document.createElement('div');
                messageDiv.id = messageId;
                messageDiv.className = `message ${data.stance}`;
                
                const formatData = JSON.parse('""" + json.dumps(DEBATE_FORMATS, ensure_ascii=False).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"') + """');
                const format = document.getElementById('format').value;
                const agents = formatData[format].agents;
                const allAgents = [...agents.support, ...agents.oppose];
                const agent = allAgents.find(a => a.name === data.agent_name) || {emoji: '🤖'};
                
                const avatarUrl = getAgentAvatar(data.agent_name);
                const avatarHtml = avatarUrl ? 
                    `<img src="${avatarUrl}" alt="${data.agent_name}" class="agent-pixel-avatar">` : 
                    `<span class="agent-emoji">${agent.emoji}</span>`;
                
                messageDiv.innerHTML = `
                    <div class="message-bubble">
                        <div class="message-header">
                            ${avatarHtml}
                            <span class="agent-name">${data.agent_name}</span>
                        </div>
                        <div class="message-content"></div>
                    </div>
                `;
                
                chatContainer.appendChild(messageDiv);
                
                streaming = {
                    element: messageDiv,
                    content: '',
                    type: 'content'
                };
                streamingMessages.set(messageId, streaming);
            }
            
            // Content 추가 (스트리밍 효과 적용)
            streaming.content += data.chunk;
            const contentElement = streaming.element.querySelector('.message-content');
            if (contentElement) {
                // 스트리밍 효과를 위한 타이핑 애니메이션
                typewriterText(contentElement, streaming.content);
                
                // 스크롤 조정
                const chatContainer = document.getElementById('chat-container');
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
        }
        
        // Argument 완료
        function onArgumentComplete(data) {
            const messageId = `${data.agent_name}-${data.round}-content`;
            const streaming = streamingMessages.get(messageId);
            
            if (streaming) {
                // 품질 점수 표시 추가
                const qualityScore = data.quality_score || 0.7;
                let qualityClass = 'quality-medium';
                let qualityText = '보통';
                
                if (qualityScore >= 0.8) {
                    qualityClass = 'quality-high';
                    qualityText = '우수';
                } else if (qualityScore < 0.6) {
                    qualityClass = 'quality-low';
                    qualityText = '개선 필요';
                }
                
                const header = streaming.element.querySelector('.message-header');
                if (header) {
                    const qualitySpan = document.createElement('span');
                    qualitySpan.className = `quality-indicator ${qualityClass}`;
                    qualitySpan.textContent = `품질: ${qualityText}`;
                    header.appendChild(qualitySpan);
                }
                
                // 에이전트 카드에서 speaking 클래스 제거
                const agentCard = document.getElementById(`${data.agent_name}-card`);
                if (agentCard) {
                    setTimeout(() => agentCard.classList.remove('speaking'), 2000);
                }
                
                // 스트리밍 상태 정리
                streamingMessages.delete(messageId);
            }
        }
        
        // Thinking 토글 함수 (업데이트된 CSS 클래스 사용)
        function toggleThinking(messageId) {
            const content = document.getElementById(`${messageId}-content`);
            const toggle = document.querySelector(`#${messageId} .thinking-toggle`);
            
            if (content && toggle) {
                if (content.classList.contains('expanded')) {
                    content.classList.remove('expanded');
                    toggle.textContent = '▶';
                    toggle.style.transform = 'rotate(-90deg)';
                } else {
                    content.classList.add('expanded');
                    toggle.textContent = '▼';
                    toggle.style.transform = 'rotate(0deg)';
                }
            }
        }
        
        // 시스템 메시지 핸들러
        function onSystemMessage(data) {
            if (data.message) {
                addSystemMessage(data.message);
            }
        }
        
        // === 픽셀아트 아바타 생성 시스템 ===
        
        // 페르소나별 아바타 특징 정의
        const avatarTraits = {
            angel: {
                baseColor: '#FFD700',
                secondaryColor: '#FFFFFF',
                features: {
                    wings: true,
                    halo: true,
                    expression: 'happy',
                    bodyType: 'ethereal'
                }
            },
            devil: {
                baseColor: '#DC143C',
                secondaryColor: '#8B0000',
                features: {
                    horns: true,
                    tail: true,
                    expression: 'mischievous',
                    bodyType: 'muscular'
                }
            },
            searcher: {
                baseColor: '#4169E1',
                secondaryColor: '#87CEEB',
                features: {
                    glasses: true,
                    magnifier: true,
                    expression: 'curious',
                    bodyType: 'normal'
                }
            },
            analyzer: {
                baseColor: '#9370DB',
                secondaryColor: '#DDA0DD',
                features: {
                    glasses: true,
                    brain: true,
                    expression: 'thinking',
                    bodyType: 'slim'
                }
            },
            writer: {
                baseColor: '#FF6347',
                secondaryColor: '#FFA07A',
                features: {
                    pen: true,
                    notebook: true,
                    expression: 'creative',
                    bodyType: 'normal'
                }
            },
            organizer: {
                baseColor: '#FFD700',
                secondaryColor: '#FFA500',
                features: {
                    microphone: true,
                    tie: true,
                    expression: 'confident',
                    bodyType: 'formal'
                }
            }
        };
        
        // 픽셀아트 생성 함수
        function generatePixelAvatar(agentName, agentRole, customPersona = null) {
            const canvas = document.createElement('canvas');
            canvas.width = 64;
            canvas.height = 64;
            const ctx = canvas.getContext('2d');
            
            // 픽셀 단위
            const pixelSize = 4;
            
            // 기본 색상 및 특징 가져오기
            const traits = avatarTraits[agentRole] || avatarTraits.searcher;
            const baseColor = traits.baseColor;
            const secondaryColor = traits.secondaryColor;
            const features = traits.features;
            
            // 커스텀 페르소나 기반 색상 변형
            if (customPersona) {
                // 페르소나 텍스트에서 색상 힌트 추출
                if (customPersona.includes('열정') || customPersona.includes('뜨거운')) {
                    traits.baseColor = '#FF6B6B';
                } else if (customPersona.includes('차분') || customPersona.includes('냉철')) {
                    traits.baseColor = '#4ECDC4';
                } else if (customPersona.includes('지혜') || customPersona.includes('현명')) {
                    traits.baseColor = '#95E1D3';
                }
            }
            
            // 배경 투명
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            // 픽셀 그리기 헬퍼 함수
            function drawPixel(x, y, color) {
                ctx.fillStyle = color;
                ctx.fillRect(x * pixelSize, y * pixelSize, pixelSize, pixelSize);
            }
            
            // 머리 그리기
            const headPattern = [
                [0,0,1,1,1,1,0,0],
                [0,1,1,1,1,1,1,0],
                [1,1,1,1,1,1,1,1],
                [1,1,1,1,1,1,1,1],
                [1,1,1,1,1,1,1,1],
                [1,1,1,1,1,1,1,1],
                [0,1,1,1,1,1,1,0],
                [0,0,1,1,1,1,0,0]
            ];
            
            // 머리 렌더링
            for (let y = 0; y < headPattern.length; y++) {
                for (let x = 0; x < headPattern[y].length; x++) {
                    if (headPattern[y][x]) {
                        drawPixel(x + 4, y + 2, baseColor);
                    }
                }
            }
            
            // 눈 그리기
            drawPixel(6, 5, '#000000');
            drawPixel(9, 5, '#000000');
            
            // 표정에 따른 입 그리기
            if (features.expression === 'happy') {
                drawPixel(6, 7, '#000000');
                drawPixel(7, 8, '#000000');
                drawPixel(8, 8, '#000000');
                drawPixel(9, 7, '#000000');
            } else if (features.expression === 'mischievous') {
                drawPixel(6, 7, '#000000');
                drawPixel(7, 7, '#000000');
                drawPixel(8, 7, '#000000');
                drawPixel(9, 8, '#000000');
            } else {
                drawPixel(6, 7, '#000000');
                drawPixel(7, 7, '#000000');
                drawPixel(8, 7, '#000000');
                drawPixel(9, 7, '#000000');
            }
            
            // 특징별 추가 요소
            if (features.halo) {
                // 후광 그리기
                for (let x = 5; x < 11; x++) {
                    drawPixel(x, 0, '#FFFF00');
                }
            }
            
            if (features.horns) {
                // 뿔 그리기
                drawPixel(5, 1, secondaryColor);
                drawPixel(4, 0, secondaryColor);
                drawPixel(10, 1, secondaryColor);
                drawPixel(11, 0, secondaryColor);
            }
            
            if (features.glasses) {
                // 안경 그리기
                drawPixel(5, 5, '#333333');
                drawPixel(6, 5, '#333333');
                drawPixel(7, 5, '#333333');
                drawPixel(8, 5, '#333333');
                drawPixel(9, 5, '#333333');
                drawPixel(10, 5, '#333333');
            }
            
            // 몸통 그리기
            const bodyPattern = [
                [0,0,1,1,1,1,0,0],
                [0,1,1,1,1,1,1,0],
                [1,1,1,1,1,1,1,1],
                [1,1,1,1,1,1,1,1],
                [1,1,1,1,1,1,1,1],
                [1,1,1,1,1,1,1,1]
            ];
            
            for (let y = 0; y < bodyPattern.length; y++) {
                for (let x = 0; x < bodyPattern[y].length; x++) {
                    if (bodyPattern[y][x]) {
                        drawPixel(x + 4, y + 10, secondaryColor);
                    }
                }
            }
            
            if (features.wings) {
                // 날개 그리기
                for (let y = 10; y < 14; y++) {
                    drawPixel(2, y, '#FFFFFF');
                    drawPixel(3, y, '#FFFFFF');
                    drawPixel(12, y, '#FFFFFF');
                    drawPixel(13, y, '#FFFFFF');
                }
            }
            
            if (features.tail) {
                // 꼬리 그리기
                drawPixel(12, 14, secondaryColor);
                drawPixel(13, 15, secondaryColor);
                drawPixel(14, 15, secondaryColor);
                drawPixel(15, 14, secondaryColor);
            }
            
            // 추가 액세서리 (역할별)
            if (agentRole === 'writer') {
                // 펜 그리기
                drawPixel(14, 12, '#000000');
                drawPixel(15, 13, '#000000');
                drawPixel(16, 14, '#FFD700');
            } else if (agentRole === 'analyzer') {
                // 돋보기 그리기
                for (let i = 0; i < 3; i++) {
                    drawPixel(1 + i, 12, '#4169E1');
                }
                drawPixel(2, 11, '#4169E1');
                drawPixel(2, 13, '#4169E1');
            } else if (agentRole === 'organizer' && features.microphone) {
                // 마이크 그리기
                drawPixel(8, 16, '#333333');
                drawPixel(8, 17, '#333333');
                drawPixel(7, 15, '#666666');
                drawPixel(8, 15, '#666666');
                drawPixel(9, 15, '#666666');
            }
            
            // 커스텀 페르소나 기반 추가 특징
            if (customPersona) {
                if (customPersona.includes('전문가') || customPersona.includes('박사')) {
                    // 박사 모자
                    for (let x = 6; x < 10; x++) {
                        drawPixel(x, 1, '#000000');
                    }
                    drawPixel(7, 0, '#FFD700');
                    drawPixel(8, 0, '#FFD700');
                } else if (customPersona.includes('창의') || customPersona.includes('예술')) {
                    // 베레모
                    drawPixel(5, 1, '#FF1493');
                    drawPixel(6, 0, '#FF1493');
                    drawPixel(7, 0, '#FF1493');
                    drawPixel(8, 0, '#FF1493');
                    drawPixel(9, 1, '#FF1493');
                }
            }
            
            return canvas.toDataURL();
        }
        
        // 아바타 캐시
        const avatarCache = new Map();
        
        // 에이전트 아바타 초기화
        function initializeAvatars() {
            const formatData = JSON.parse('""" + json.dumps(DEBATE_FORMATS, ensure_ascii=False).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"') + """');
            const format = document.getElementById('format').value;
            
            // 캐시 초기화
            avatarCache.clear();
            
            if (format === 'custom' && window.customAgentsConfig) {
                // 커스텀 에이전트 아바타 생성
                const customConfig = window.customAgentsConfig;
                
                // A팀 에이전트
                customConfig.support.forEach(agent => {
                    const avatarUrl = generatePixelAvatar(agent.name, agent.role, agent.persona);
                    avatarCache.set(agent.name, avatarUrl);
                    
                    const card = document.getElementById(`${agent.name}-card`);
                    if (card) {
                        const avatarDiv = card.querySelector('.agent-avatar');
                        if (avatarDiv) {
                            avatarDiv.innerHTML = `<img src="${avatarUrl}" alt="${agent.name}" class="agent-pixel-avatar">`;
                        }
                    }
                });
                
                // B팀 에이전트
                customConfig.oppose.forEach(agent => {
                    const avatarUrl = generatePixelAvatar(agent.name, agent.role, agent.persona);
                    avatarCache.set(agent.name, avatarUrl);
                    
                    const card = document.getElementById(`${agent.name}-card`);
                    if (card) {
                        const avatarDiv = card.querySelector('.agent-avatar');
                        if (avatarDiv) {
                            avatarDiv.innerHTML = `<img src="${avatarUrl}" alt="${agent.name}" class="agent-pixel-avatar">`;
                        }
                    }
                });
                
                // 진행자 아바타
                const organizerAvatar = generatePixelAvatar(customConfig.organizer.name, 'organizer');
                avatarCache.set(customConfig.organizer.name, organizerAvatar);
            } else {
                // 기본 형식 아바타 생성
                const agents = formatData[format].agents;
                
                // 모든 에이전트에 대해 아바타 생성
                [...agents.support, ...agents.oppose].forEach(agent => {
                    const avatarUrl = generatePixelAvatar(agent.name, agent.role);
                    avatarCache.set(agent.name, avatarUrl);
                    
                    const card = document.getElementById(`${agent.name}-card`);
                    if (card) {
                        const avatarDiv = card.querySelector('.agent-avatar');
                        if (avatarDiv) {
                            avatarDiv.innerHTML = `<img src="${avatarUrl}" alt="${agent.name}" class="agent-pixel-avatar">`;
                        }
                    }
                });
                
                // 진행자 아바타도 생성
                const organizerData = formatData[format].organizer;
                const organizerAvatar = generatePixelAvatar(organizerData.name, 'organizer');
                avatarCache.set(organizerData.name, organizerAvatar);
            }
        }
        
        // 아바타 가져오기
        function getAgentAvatar(agentName) {
            return avatarCache.get(agentName) || '';
        }
        
        // 시스템 메시지 추가
        function addSystemMessage(text) {
            const chatContainer = document.getElementById('chat-container');
            const message = document.createElement('div');
            // 애니메이션 제거 - 깜빡거림 방지
            message.style.textAlign = 'center';
            message.style.margin = '20px 0';
            message.style.color = '#FFD700';
            message.style.fontWeight = 'bold';
            message.textContent = text;
            
            chatContainer.appendChild(message);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        // 상태 업데이트
        function updateStatus(text, online) {
            document.getElementById('status-text').textContent = text;
            const dot = document.getElementById('status-dot');
            if (online) {
                dot.classList.remove('offline');
            } else {
                dot.classList.add('offline');
            }
        }
        
        // 타이머
        function startTimer() {
            timerInterval = setInterval(() => {
                const elapsed = Math.floor((Date.now() - debateStartTime) / 1000);
                const minutes = Math.floor(elapsed / 60);
                const seconds = elapsed % 60;
                document.getElementById('debate-timer').textContent = 
                    `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }, 1000);
        }
        
        function stopTimer() {
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            }
        }
        
        // === 자동 모드/사용자 변경 시스템 ===
        
        // 토론 형식 변경 시 자동으로 모드와 사용자 업데이트
        function autoUpdateModeAndUsers(format) {
            const formatData = JSON.parse('""" + json.dumps(DEBATE_FORMATS, ensure_ascii=False).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"') + """');
            const selected = formatData[format];
            
            if (!selected) return;
            
            // 🎯 즉시 시각적 피드백 제공
            showFormatChangeNotification(format, selected);
            
            // 🔄 팀 구성 자동 업데이트
            updateTeamDisplay(selected);
            
            // 🏷️ 라벨 자동 변경
            document.getElementById('support-label').textContent = selected.support_team;
            document.getElementById('oppose-label').textContent = selected.oppose_team;
            
            // 🎭 에이전트 카드 애니메이션 효과
            animateAgentCards();
            
            // 📊 형식별 추천 설정 자동 적용
            applyFormatRecommendations(format, selected);
        }
        
        // 형식 변경 알림 표시
        function showFormatChangeNotification(format, formatConfig) {
            const notification = document.createElement('div');
            notification.style.cssText = `
                position: fixed; top: 20px; right: 20px; z-index: 9999;
                background: linear-gradient(45deg, #667eea, #764ba2);
                color: white; padding: 15px 20px; border-radius: 10px;
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3);
                font-weight: bold; /* animation 제거 - 깜빡거림 방지 */
            `;
            
            const formatNames = {
                'adversarial': '대립형 토론',
                'collaborative': '협력형 토론', 
                'competitive': '경쟁형 토론'
            };
            
            notification.innerHTML = `
                🔄 <strong>${formatNames[format] || format}</strong>으로 변경됨<br>
                <small style="opacity: 0.9;">팀: ${formatConfig.support_team} vs ${formatConfig.oppose_team}</small>
            `;
            
            document.body.appendChild(notification);
            
            // 3초 후 자동 제거
            setTimeout(() => {
                // 애니메이션 제거 - 깜빡거림 방지
                setTimeout(() => notification.remove(), 300);
            }, 3000);
        }
        
        // 에이전트 카드 애니메이션
        function animateAgentCards() {
            const cards = document.querySelectorAll('.agent-card');
            cards.forEach((card, index) => {
                // 애니메이션 제거 - 깜빡거림 방지
            });
        }
        
        // 형식별 추천 설정 적용
        function applyFormatRecommendations(format, formatConfig) {
            const recommendations = {
                'adversarial': {
                    rounds: 3,
                    temperature: 0.9,
                    description: '🔥 격렬한 대립 토론'
                },
                'collaborative': {
                    rounds: 4,
                    temperature: 0.7,
                    description: '🤝 협력적 사고 교환'
                },
                'competitive': {
                    rounds: 5,
                    temperature: 0.8,
                    description: '⚔️ 전략적 경쟁 토론'
                }
            };
            
            const rec = recommendations[format];
            if (rec) {
                // 라운드 수 자동 조정
                document.getElementById('rounds').value = rec.rounds;
                
                // VS 표시기 업데이트
                const vsIndicator = document.getElementById('vs-indicator');
                if (vsIndicator) {
                    vsIndicator.innerHTML = `
                        <div style="text-align: center;">
                            <div style="font-size: 0.8em; opacity: 0.8;">${rec.description}</div>
                            <div style="font-size: 1.5em; margin-top: 5px;">⚔️ VS ⚔️</div>
                        </div>
                    `;
                }
            }
        }
        
        // === 향상된 커스텀 모드 기능 ===
        
        // 커스텀 에이전트 필드 업데이트
        function updateCustomAgentFields() {
            const membersPerTeam = parseInt(document.getElementById('members-per-team').value);
            const configDiv = document.getElementById('custom-agents-config');
            
            let html = '<h4 style="color: #667eea; margin: 15px 0 10px 0;">에이전트 세부 설정</h4>';
            
            // A팀 에이전트 설정
            html += '<div style="border: 1px solid rgba(39, 174, 96, 0.3); border-radius: 5px; padding: 10px; margin-bottom: 10px;">';
            html += '<h5 style="color: #27ae60; margin-bottom: 10px;">A팀 에이전트</h5>';
            
            for (let i = 0; i < membersPerTeam; i++) {
                html += `
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; margin-bottom: 8px;">
                        <input type="text" id="team-a-agent-${i}-name" placeholder="이름" value="A팀_${i+1}">
                        <input type="text" id="team-a-agent-${i}-emoji" placeholder="이모지" value="🙂" maxlength="2">
                        <select id="team-a-agent-${i}-role">
                            <option value="writer">작가</option>
                            <option value="analyzer">분석가</option>
                            <option value="searcher">탐색가</option>
                            <option value="reviewer">검토자</option>
                            <option value="angel">천사</option>
                            <option value="devil">악마</option>
                        </select>
                    </div>
                    <textarea id="team-a-agent-${i}-persona" placeholder="이 에이전트의 성격과 전문성을 설명하세요" 
                             style="width: 100%; height: 60px; margin-bottom: 10px; font-size: 12px;"></textarea>
                `;
            }
            html += '</div>';
            
            // B팀 에이전트 설정
            html += '<div style="border: 1px solid rgba(231, 76, 60, 0.3); border-radius: 5px; padding: 10px;">';
            html += '<h5 style="color: #e74c3c; margin-bottom: 10px;">B팀 에이전트</h5>';
            
            for (let i = 0; i < membersPerTeam; i++) {
                html += `
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; margin-bottom: 8px;">
                        <input type="text" id="team-b-agent-${i}-name" placeholder="이름" value="B팀_${i+1}">
                        <input type="text" id="team-b-agent-${i}-emoji" placeholder="이모지" value="🙃" maxlength="2">
                        <select id="team-b-agent-${i}-role">
                            <option value="writer">작가</option>
                            <option value="analyzer">분석가</option>
                            <option value="searcher">탐색가</option>
                            <option value="reviewer">검토자</option>
                            <option value="angel">천사</option>
                            <option value="devil">악마</option>
                        </select>
                    </div>
                    <textarea id="team-b-agent-${i}-persona" placeholder="이 에이전트의 성격과 전문성을 설명하세요" 
                             style="width: 100%; height: 60px; margin-bottom: 10px; font-size: 12px;"></textarea>
                `;
            }
            html += '</div>';
            
            configDiv.innerHTML = html;
        }
        
        // 커스텀 프리셋 적용
        function applyCustomPreset() {
            const style = document.getElementById('custom-style').value;
            const membersPerTeam = parseInt(document.getElementById('members-per-team').value);
            
            const presets = {
                academic: {
                    teamA: {
                        name: '연구팀 A',
                        agents: [
                            {name: '연구자A', emoji: '🔬', role: 'searcher', persona: '과학적 연구와 데이터 분석에 능숙한 전문가입니다. 객관적 사실과 통계를 바탕으로 논증합니다.'},
                            {name: '논리학자A', emoji: '🧠', role: 'analyzer', persona: '논리적 사고와 비판적 분석을 전문으로 하는 철학자입니다. 논증의 구조와 타당성을 면밀히 검토합니다.'}
                        ]
                    },
                    teamB: {
                        name: '연구팀 B',
                        agents: [
                            {name: '연구자B', emoji: '📊', role: 'searcher', persona: '대안적 관점에서 연구하는 반대 연구팀입니다. 다양한 방법론과 대안 이론을 제시합니다.'},
                            {name: '논리학자B', emoji: '🔍', role: 'analyzer', persona: '기존 이론의 한계를 지적하고 새로운 관점을 제시하는 비판적 사고가입니다.'}
                        ]
                    }
                },
                business: {
                    teamA: {
                        name: '비즈니스 컨설턴트',
                        agents: [
                            {name: '전략기획자A', emoji: '📈', role: 'writer', persona: 'ROI와 비즈니스 가치를 중심으로 전략을 수립하는 전문가입니다. 실용적이고 수익성 있는 제안을 합니다.'},
                            {name: '시장분석가A', emoji: '📊', role: 'analyzer', persona: '시장 동향과 경쟁 분석을 통해 데이터 기반의 통찰을 제공하는 전문가입니다.'}
                        ]
                    },
                    teamB: {
                        name: '비즈니스 자문단',
                        agents: [
                            {name: '전략기획자B', emoji: '📋', role: 'writer', persona: '대안적 비즈니스 모델과 전략을 제시하는 혁신적 사고가입니다.'},
                            {name: '리스크분석가B', emoji: '⚠️', role: 'reviewer', persona: '비즈니스 리스크와 비용을 면밀히 분석하여 신중한 결정을 도와주는 전문가입니다.'}
                        ]
                    }
                }
            };
            
            if (style !== 'custom' && presets[style]) {
                const preset = presets[style];
                
                // 팀 이름 업데이트
                document.getElementById('team-a-name').value = preset.teamA.name;
                document.getElementById('team-b-name').value = preset.teamB.name;
                
                // 에이전트 설정 업데이트
                for (let i = 0; i < Math.min(membersPerTeam, preset.teamA.agents.length); i++) {
                    const agent = preset.teamA.agents[i];
                    document.getElementById(`team-a-agent-${i}-name`).value = agent.name;
                    document.getElementById(`team-a-agent-${i}-emoji`).value = agent.emoji;
                    document.getElementById(`team-a-agent-${i}-role`).value = agent.role;
                    document.getElementById(`team-a-agent-${i}-persona`).value = agent.persona;
                }
                
                for (let i = 0; i < Math.min(membersPerTeam, preset.teamB.agents.length); i++) {
                    const agent = preset.teamB.agents[i];
                    document.getElementById(`team-b-agent-${i}-name`).value = agent.name;
                    document.getElementById(`team-b-agent-${i}-emoji`).value = agent.emoji;
                    document.getElementById(`team-b-agent-${i}-role`).value = agent.role;
                    document.getElementById(`team-b-agent-${i}-persona`).value = agent.persona;
                }
            }
        }
        
        // 커스텀 에이전트 생성
        function generateCustomAgents() {
            const membersPerTeam = parseInt(document.getElementById('members-per-team').value);
            
            // 커스텀 에이전트 설정 수집
            const customAgents = {
                support: [],
                oppose: [],
                support_team: document.getElementById('team-a-name').value,
                oppose_team: document.getElementById('team-b-name').value,
                organizer: {
                    name: document.getElementById('organizer-name').value,
                    role: 'organizer',
                    emoji: '🎯'
                }
            };
            
            // A팀 에이전트 수집
            for (let i = 0; i < membersPerTeam; i++) {
                const name = document.getElementById(`team-a-agent-${i}-name`).value;
                const emoji = document.getElementById(`team-a-agent-${i}-emoji`).value;
                const role = document.getElementById(`team-a-agent-${i}-role`).value;
                const persona = document.getElementById(`team-a-agent-${i}-persona`).value;
                
                customAgents.support.push({
                    name: name || `A팀_${i+1}`,
                    emoji: emoji || '🙂',
                    role: role,
                    persona: persona || `당신은 ${name || `A팀_${i+1}`}입니다. ${role} 역할을 담당합니다.`
                });
            }
            
            // B팀 에이전트 수집
            for (let i = 0; i < membersPerTeam; i++) {
                const name = document.getElementById(`team-b-agent-${i}-name`).value;
                const emoji = document.getElementById(`team-b-agent-${i}-emoji`).value;
                const role = document.getElementById(`team-b-agent-${i}-role`).value;
                const persona = document.getElementById(`team-b-agent-${i}-persona`).value;
                
                customAgents.oppose.push({
                    name: name || `B팀_${i+1}`,
                    emoji: emoji || '🙃',
                    role: role,
                    persona: persona || `당신은 ${name || `B팀_${i+1}`}입니다. ${role} 역할을 담당합니다.`
                });
            }
            
            // 전역 변수에 저장
            window.customAgentsConfig = customAgents;
            
            // 팀 디스플레이 업데이트
            updateTeamDisplay({
                support_team: customAgents.support_team,
                oppose_team: customAgents.oppose_team,
                agents: {
                    support: customAgents.support,
                    oppose: customAgents.oppose
                }
            });
            
            // 라벨 업데이트
            document.getElementById('support-label').textContent = customAgents.support_team;
            document.getElementById('oppose-label').textContent = customAgents.oppose_team;
            
            // 픽셀아트 아바타 초기화
            initializeAvatars();
            
            alert('🎉 커스텀 에이전트 구성이 생성되었습니다!');
        }
        
        // 페르소나 미리보기
        function previewPersonas() {
            const membersPerTeam = parseInt(document.getElementById('members-per-team').value);
            let preview = '👁️ **페르소나 미리보기**\\n\\n';
            
            // A팀 페르소나
            preview += `🟩 **${document.getElementById('team-a-name').value}**\\n`;
            for (let i = 0; i < membersPerTeam; i++) {
                const name = document.getElementById(`team-a-agent-${i}-name`).value;
                const emoji = document.getElementById(`team-a-agent-${i}-emoji`).value;
                const role = document.getElementById(`team-a-agent-${i}-role`).value;
                const persona = document.getElementById(`team-a-agent-${i}-persona`).value;
                
                preview += `${emoji} **${name}** (${role})\\n`;
                preview += `"${persona || '기본 페르소나'}입니다."\\n\\n`;
            }
            
            // B팀 페르소나
            preview += `🟥 **${document.getElementById('team-b-name').value}**\\n`;
            for (let i = 0; i < membersPerTeam; i++) {
                const name = document.getElementById(`team-b-agent-${i}-name`).value;
                const emoji = document.getElementById(`team-b-agent-${i}-emoji`).value;
                const role = document.getElementById(`team-b-agent-${i}-role`).value;
                const persona = document.getElementById(`team-b-agent-${i}-persona`).value;
                
                preview += `${emoji} **${name}** (${role})\\n`;
                preview += `"${persona || '기본 페르소나'}입니다."\\n\\n`;
            }
            
            // 모달 윈도우로 표시
            const modal = document.createElement('div');
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0,0,0,0.8); z-index: 10000;
                display: flex; justify-content: center; align-items: center;
            `;
            
            const content = document.createElement('div');
            content.style.cssText = `
                background: #1a1a2e; border-radius: 10px; padding: 20px;
                max-width: 600px; max-height: 80vh; overflow-y: auto;
                border: 1px solid #667eea;
            `;
            
            content.innerHTML = `
                <h3 style="color: #667eea; margin-bottom: 15px;">👁️ 페르소나 미리보기</h3>
                <pre style="color: #e0e0e0; line-height: 1.6; white-space: pre-wrap;">${preview}</pre>
                <button onclick="this.parentElement.parentElement.remove()" 
                        style="padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; margin-top: 15px;">
                    닫기
                </button>
            `;
            
            modal.appendChild(content);
            document.body.appendChild(modal);
            
            // 배경 클릭 시 닫기
            modal.addEventListener('click', (e) => {
                if (e.target === modal) modal.remove();
            });
        }
    </script>
</body>
</html>
"""

@app.get("/favicon.ico")
async def favicon():
    return HTMLResponse("", status_code=204)

@app.get("/api/models")
async def get_models():
    """사용 가능한 Ollama 모델 목록"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{OLLAMA_API_URL}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get("models", []):
                    models.append({
                        "name": model["name"],
                        "size": model["details"].get("parameter_size", "Unknown"),
                        "family": model["details"].get("family", "Unknown")
                    })
                return {"models": models, "success": True}
            else:
                return {"models": [], "success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"models": [], "success": False, "error": str(e)}

@app.get("/api/status")
async def get_status():
    """서버 상태"""
    return {
        "status": "online",
        "active_debates": len(active_debates)
    }

@app.get("/api/ollama/status")
async def get_ollama_status():
    """Ollama 서버 상태 확인"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_API_URL}/api/tags")
            if response.status_code == 200:
                return {"status": "online", "success": True}
            else:
                return {"status": "offline", "success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"status": "offline", "success": False, "error": str(e)}

class DebateRequest(BaseModel):
    topic: str
    format: str
    max_rounds: int
    model: str
    language: str
    support_agents: List[Dict]
    oppose_agents: List[Dict]
    custom_config: Optional[Dict] = None

@app.post("/api/debate/start")
async def start_debate(request: DebateRequest, background_tasks: BackgroundTasks):
    """토론 시작"""
    try:
        session_id = str(uuid.uuid4())
        
        # 토론 설정
        config = DebateConfig(
            topic=request.topic,
            format=DebateFormat[request.format.upper()],
            max_rounds=request.max_rounds
        )
        
        # 한국어 프롬프트 추가
        korean_prompt = "한국어로 답변해주세요. " if request.language == "ko" else ""
        
        # 토론 형식 정보 가져오기
        format_data = DEBATE_FORMATS[request.format]
        
        # ORGANIZER 생성
        organizer_config = format_data['organizer']
        organizer = DebateAgent(
            name=organizer_config['name'],
            role=AgentRole.ORGANIZER,
            stance=DebateStance.NEUTRAL,
            model=request.model,
            persona_prompt=korean_prompt + f"당신은 {organizer_config['name']}입니다.",
            temperature=0.7
        )
        
        # 에이전트 생성 (Context7 연구 기반 향상된 페르소나 시스템)
        support_agents = []
        for agent_config in request.support_agents:
            # 커스텀 페르소나 처리 (Context7 Generator-Critic 프레임워크 적용)
            if request.custom_config and agent_config.get('persona'):
                enhanced_persona = f"""
{korean_prompt}

🎭 **캐릭터 정의**: 당신은 {agent_config['name']}입니다.

📝 **전문 페르소나**: {agent_config['persona']}

🎯 **역할 특화**: {agent_config['role']} 역할을 담당하며, 다음과 같은 특성을 가집니다:
- 일관된 성격과 어조 유지
- 전문 분야에 대한 깊은 지식 
- 상대방과의 상호작용에서 캐릭터 특성 반영
- 논증 스타일과 접근 방식에서 개성 표현

💬 **응답 가이드라인**:
- 캐릭터의 배경과 전문성을 자연스럽게 반영
- 일관된 어조와 관점 유지
- {agent_config['emoji']} 이모티콘을 적절히 활용
- 3-5문장으로 명확하고 설득력 있게 표현
            """
            else:
                enhanced_persona = korean_prompt + f"당신은 {agent_config['name']}입니다."
            
            agent = DebateAgent(
                name=agent_config['name'],
                role=AgentRole[agent_config['role'].upper()],
                stance=DebateStance.SUPPORT,
                model=request.model,
                persona_prompt=enhanced_persona,
                temperature=0.8
            )
            support_agents.append(agent)
        
        oppose_agents = []
        for agent_config in request.oppose_agents:
            # 커스텀 페르소나 처리 (Context7 연구 기반)
            if request.custom_config and agent_config.get('persona'):
                enhanced_persona = f"""
{korean_prompt}

🎭 **캐릭터 정의**: 당신은 {agent_config['name']}입니다.

📝 **전문 페르소나**: {agent_config['persona']}

🎯 **역할 특화**: {agent_config['role']} 역할을 담당하며, 다음과 같은 특성을 가집니다:
- 일관된 성격과 어조 유지
- 전문 분야에 대한 깊은 지식
- 상대방과의 상호작용에서 캐릭터 특성 반영
- 논증 스타일과 접근 방식에서 개성 표현

💬 **응답 가이드라인**:
- 캐릭터의 배경과 전문성을 자연스럽게 반영
- 일관된 어조와 관점 유지
- {agent_config['emoji']} 이모티콘을 적절히 활용
- 3-5문장으로 명확하고 설득력 있게 표현
            """
            else:
                enhanced_persona = korean_prompt + f"당신은 {agent_config['name']}입니다."
            
            agent = DebateAgent(
                name=agent_config['name'],
                role=AgentRole[agent_config['role'].upper()],
                stance=DebateStance.OPPOSE,
                model=request.model,
                persona_prompt=enhanced_persona,
                temperature=0.8
            )
            oppose_agents.append(agent)
        
        # 컨트롤러 생성
        controller = DebateController(config, support_agents, oppose_agents)
        
        # 세션 저장
        session = DebateSession(session_id, config)
        session.controller = controller
        session.support_agents = support_agents
        session.oppose_agents = oppose_agents
        session.organizer = organizer  # ORGANIZER 추가
        active_debates[session_id] = session
        
        # 토론 시작
        controller.start_debate()
    
        # 자동 진행
        background_tasks.add_task(conduct_debate_async, session, request.language)
        
        return {"session_id": session_id, "status": "started"}
        
    except KeyError as e:
        print(f"KeyError in start_debate: {e}")
        raise HTTPException(status_code=400, detail=f"잘못된 설정값: {str(e)}")
    except Exception as e:
        print(f"Error in start_debate: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"토론 시작 중 오류 발생: {str(e)}")

async def conduct_debate_async(session: DebateSession, language: str):
    """향상된 토론 진행 - 랜덤 턴테이킹 및 진행자 적극 개입"""
    controller = session.controller
    korean_context = "한국어로 토론하세요. " if language == "ko" else ""
    
    await asyncio.sleep(2)
    
    # ORGANIZER 토론 시작 인사 (스트리밍 방식)
    organizer_intro = await broadcast_argument_streaming(
        session,
        session.organizer,
        controller.config.topic,
        [],
        0,
        f"{korean_context}토론을 시작하겠습니다. 주제: '{controller.config.topic}'. 모든 참가자는 자유롭게 의견을 표현해주세요."
    )
    await asyncio.sleep(3)
    
    # 점수 초기화
    support_score = 0.5
    oppose_score = 0.5
    
    # 라운드별 진행
    for round_num in range(1, controller.config.max_rounds + 1):
        # 세션 상태 확인
        if session.session_id not in active_debates:
            print(f"세션 {session.session_id} 종료됨, 토론 중단")
            break
            
        # 라운드 시작 알림
        print(f"🔔 라운드 {round_num} 시작 (세션: {session.session_id})")
        controller.current_round = round_num
        
        await broadcast_message(session, {
            "type": "round_start",
            "data": {"round": round_num}
        })
        
        await asyncio.sleep(2)
        
        # 이번 라운드에 발언할 에이전트 목록 준비
        all_agents = []
        
        # 지지팀과 반대팀 에이전트 모두 포함
        for agent in session.support_agents:
            all_agents.append(("support", agent))
        for agent in session.oppose_agents:
            all_agents.append(("oppose", agent))
        
        # 랜덤하게 섞기
        random.shuffle(all_agents)
        
        # 발언 순서 알림
        speaker_names = [agent[1].name for agent in all_agents]
        await broadcast_message(session, {
            "type": "system",
            "data": {"message": f"🎲 라운드 {round_num} 발언 순서: {' → '.join(speaker_names)}"}
        })
        await asyncio.sleep(2)
        
        # 각 에이전트가 순서대로 발언
        for idx, (team, agent) in enumerate(all_agents):
            # 중간에 진행자 개입 (2명 발언 후마다)
            if idx > 0 and idx % 2 == 0 and idx < len(all_agents) - 1:
                await asyncio.sleep(2)
                
                # 진행자 중간 정리
                organizer_prompt = f"{korean_context}지금까지 {speaker_names[idx-2]}와 {speaker_names[idx-1]}의 발언을 간단히 정리하고, 다음 발언자에게 논점을 제시해주세요."
                
                organizer_interjection = await broadcast_argument_streaming(
                    session,
                    session.organizer,
                    controller.config.topic,
                    controller.debate_history,
                    round_num,
                    organizer_prompt
                )
                await asyncio.sleep(2)
            
            # 타이핑 표시
            await broadcast_message(session, {
                "type": "typing",
                "data": {
                    "agent_name": agent.name,
                    "stance": team
                }
            })
            
            await asyncio.sleep(2)
            
            # 발언 프롬프트 생성 (컨텍스트 인식)
            if idx == 0:
                prompt = f"{korean_context}라운드 {round_num}의 첫 발언자입니다. '{controller.config.topic}'에 대한 당신의 입장을 명확히 제시하세요."
            else:
                last_speaker = all_agents[idx-1][1].name
                prompt = f"{korean_context}{last_speaker}의 발언에 이어서, 당신의 관점을 제시하세요. 이전 발언을 고려하여 응답하세요."
            
            # 스트리밍으로 논증 생성 및 전송
            arg = await broadcast_argument_streaming(
                session,
                agent,
                controller.config.topic,
                controller.debate_history,
                round_num,
                prompt
            )
            
            controller.debate_history.append(arg)
            
            # 다음 발언자 대기 (동시 발언 방지)
            await asyncio.sleep(3)
        
        # 라운드 평가
        support_score = 0.5 + (round_num * 0.1) + random.uniform(-0.05, 0.05)
        oppose_score = 0.5 + (round_num * 0.08) + random.uniform(-0.05, 0.05)
        
        await broadcast_evaluation(session, {
            "support_team": min(support_score, 0.95),
            "oppose_team": min(oppose_score, 0.95)
        })
        
        # 라운드 완료
        await broadcast_message(session, {
            "type": "round_complete",
            "data": {"round": round_num}
        })
        
        # ORGANIZER 라운드 종합 요약
        await asyncio.sleep(2)
        
        organizer_summary = await broadcast_argument_streaming(
            session,
            session.organizer,
            controller.config.topic,
            controller.debate_history,
            round_num,
            f"{korean_context}라운드 {round_num} 종합 정리: 이번 라운드의 핵심 쟁점과 각 팀의 주요 논점을 정리하고, 다음 라운드의 방향을 제시해주세요."
        )
        await asyncio.sleep(2)
    
    # 토론 종료 - ORGANIZER 최종 판정
    await asyncio.sleep(2)
    winner = "support" if support_score > oppose_score else "oppose"
    
    # ORGANIZER 최종 결론 (스트리밍 방식)
    organizer_conclusion = await broadcast_argument_streaming(
        session,
        session.organizer,
        controller.config.topic,
        controller.debate_history,
        controller.config.max_rounds + 1,
        f"{korean_context}토론 최종 결론: 전체 토론을 종합하여 승부를 판정하고 시사점을 제시해주세요. 점수 - 지지팀: {support_score:.2f}, 반대팀: {oppose_score:.2f}"
    )
    await asyncio.sleep(2)
    
    await broadcast_message(session, {
        "type": "debate_complete",
        "data": {
            "winner": winner,
            "support_score": support_score,
            "oppose_score": oppose_score
        }
    })

async def broadcast_argument(session: DebateSession, argument):
    """논증 전송 (KITECH 방식 품질 점수 포함)"""
    message = {
        "type": "argument",
        "data": {
            "agent_name": argument.agent_name,
            "stance": argument.stance.value,
            "content": argument.content,
            "round": argument.round_number,
            "confidence_score": argument.confidence_score,
            "quality_score": getattr(argument, 'quality_score', 0.7),  # KITECH 품질 점수
            "evidence": getattr(argument, 'evidence', [])  # 증거 목록
        }
    }
    await broadcast_message(session, message)

async def broadcast_argument_streaming(session: DebateSession, agent, topic, context, round_num, prompt):
    """스트리밍 방식으로 논증 전송 (향상된 신뢰성)"""
    thinking_chunks = []
    content_chunks = []
    max_retries = 3
    retry_delay = 2
    
    # 스트리밍 콜백 정의
    async def stream_callback(message_type, chunk):
        if message_type == 'thinking_start':
            await broadcast_message(session, {
                "type": "thinking_start",
                "data": {
                    "agent_name": agent.name,
                    "stance": agent.stance.value,
                    "round": round_num
                }
            })
        elif message_type == 'thinking_chunk':
            thinking_chunks.append(chunk)
            await broadcast_message(session, {
                "type": "thinking_chunk",
                "data": {
                    "agent_name": agent.name,
                    "chunk": chunk
                }
            })
        elif message_type == 'thinking_complete':
            await broadcast_message(session, {
                "type": "thinking_complete",
                "data": {
                    "agent_name": agent.name,
                    "thinking_content": ''.join(thinking_chunks)
                }
            })
            thinking_chunks.clear()
        elif message_type == 'content_chunk':
            content_chunks.append(chunk)
            await broadcast_message(session, {
                "type": "content_chunk",
                "data": {
                    "agent_name": agent.name,
                    "chunk": chunk,
                    "stance": agent.stance.value
                }
            })
    
    # 재시도 로직이 포함된 논증 생성
    argument = None
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # 타임아웃 설정 (30초)
            argument = await asyncio.wait_for(
                agent.generate_argument(
                    topic,
                    context,
                    round_num,
                    prompt,
                    stream_callback=stream_callback
                ),
                timeout=30.0
            )
            
            # 성공적으로 생성된 경우
            if argument and argument.content:
                break
                
        except asyncio.TimeoutError:
            last_error = "응답 시간 초과"
            print(f"⏰ {agent.name} 응답 타임아웃 (시도 {attempt + 1}/{max_retries})")
            
        except Exception as e:
            last_error = str(e)
            print(f"❌ {agent.name} 응답 생성 실패 (시도 {attempt + 1}/{max_retries}): {e}")
        
        # 재시도 전 대기
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= 1.5  # 점진적 대기 시간 증가
            
            # 재시도 알림
            await broadcast_message(session, {
                "type": "system",
                "data": {
                    "message": f"🔄 {agent.name}의 응답을 재시도하고 있습니다... (시도 {attempt + 2}/{max_retries})"
                }
            })
    
    # 모든 재시도 실패 시 폴백 응답
    if not argument or not argument.content:
        print(f"⚠️ {agent.name} 폴백 응답 사용")
        
        # 폴백 응답 생성
        from debate_agent import Argument
        argument = Argument(
            content=f"[기술적 문제로 {agent.name}의 응답이 일시적으로 지연되었습니다. 다음 라운드에서 더 나은 논증을 제시하겠습니다.]",
            agent_name=agent.name,
            stance=agent.stance,
            round_number=round_num,
            evidence=[],
            confidence_score=0.5,
            quality_score=0.5
        )
        
        # 오류 알림
        await broadcast_message(session, {
            "type": "system",
            "data": {
                "message": f"⚠️ {agent.name}의 응답 생성에 문제가 발생했습니다. 임시 응답으로 대체합니다.",
                "error": last_error
            }
        })
    
    # 최종 논증 완성 메시지
    await broadcast_message(session, {
        "type": "argument_complete",
        "data": {
            "agent_name": argument.agent_name,
            "stance": argument.stance.value,
            "content": argument.content,
            "round": argument.round_number,
            "confidence_score": argument.confidence_score,
            "quality_score": getattr(argument, 'quality_score', 0.7),
            "evidence": getattr(argument, 'evidence', []),
            "thinking_content": getattr(argument, 'thinking_content', '')
        }
    })
    
    return argument

async def broadcast_evaluation(session: DebateSession, scores):
    """평가 전송"""
    message = {
        "type": "evaluation",
        "data": scores
    }
    await broadcast_message(session, message)

async def broadcast_message(session: DebateSession, message):
    """Context7 기반: 강화된 메시지 브로드캐스트"""
    disconnected = []
    broadcast_start = asyncio.get_event_loop().time()
    successful_sends = 0
    
    # 메시지에 타임스탬프 및 메타데이터 추가
    enhanced_message = {
        **message,
        "metadata": {
            "timestamp": broadcast_start * 1000,  # milliseconds
            "session_id": session.session_id,
            "broadcast_id": str(uuid.uuid4())[:8]
        }
    }
    
    # 병렬 브로드캐스트 (Context7 최적화)
    send_tasks = []
    for client in session.clients:
        task = asyncio.create_task(safe_send_message(client, enhanced_message))
        send_tasks.append((client, task))
    
    # 결과 수집 및 처리
    for client, task in send_tasks:
        try:
            success = await asyncio.wait_for(task, timeout=5.0)
            if success:
                successful_sends += 1
            else:
                disconnected.append(client)
        except asyncio.TimeoutError:
            print(f"⚠️ 클라이언트 {id(client)} 타임아웃")
            disconnected.append(client)
        except Exception as e:
            print(f"❌ 클라이언트 {id(client)} 전송 실패: {e}")
            disconnected.append(client)
    
    # 연결 해제된 클라이언트 정리
    for client in disconnected:
        if client in session.clients:
            session.clients.remove(client)
    
    # 브로드캐스트 성능 모니터링
    broadcast_time = (asyncio.get_event_loop().time() - broadcast_start) * 1000
    if broadcast_time > 100:  # 100ms 초과시 경고
        print(f"⚠️ 느린 브로드캐스트: {broadcast_time:.2f}ms, 성공: {successful_sends}/{len(send_tasks)}")

async def safe_send_message(client, message):
    """안전한 메시지 전송"""
    try:
        await client.send_json(message)
        return True
    except Exception as e:
        print(f"클라이언트 전송 실패: {e}")
        return False

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Context7 기반: 강화된 WebSocket 연결 관리"""
    client_id = str(uuid.uuid4())[:8]
    connection_time = asyncio.get_event_loop().time()
    
    try:
        # 연결 수락
        await websocket.accept()
        print(f"🔗 WebSocket 연결: {client_id} → {session_id}")
        
        # 세션 유효성 검증
        if session_id not in active_debates:
            await websocket.close(code=1008, reason="Invalid session")
            print(f"❌ 잘못된 세션: {session_id}")
            return
        
        session = active_debates[session_id]
        session.clients.append(websocket)
        
        # 연결 확인 메시지
        await safe_send_message(websocket, {
            "type": "connection_confirmed",
            "data": {
                "client_id": client_id,
                "session_id": session_id,
                "server_time": connection_time * 1000,
                "status": "connected"
            }
        })
        
        # Context7 기반: 하트비트 및 상태 동기화
        heartbeat_task = asyncio.create_task(heartbeat_manager(websocket, client_id))
        
        try:
            while True:
                # 메시지 수신 대기 (타임아웃 설정)
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    
                    # 클라이언트 메시지 처리
                    await handle_client_message(websocket, session, data, client_id)
                    
                except asyncio.TimeoutError:
                    # 하트비트 체크
                    print(f"🔄 하트비트 체크: {client_id}")
                    continue
                    
                except WebSocketDisconnect:
                    print(f"🔌 클라이언트 연결 해제: {client_id}")
                    break
                    
        except Exception as e:
            print(f"❌ WebSocket 오류: {client_id} - {e}")
            
        finally:
            # 정리 작업
            heartbeat_task.cancel()
            if websocket in session.clients:
                session.clients.remove(websocket)
            
            print(f"🧹 클라이언트 정리 완료: {client_id}")
            
            # 마지막 클라이언트인 경우 세션 정리
            if not session.clients and session_id in active_debates:
                print(f"🗑️ 빈 세션 정리: {session_id}")
                del active_debates[session_id]
                
    except Exception as e:
        print(f"❌ WebSocket 연결 실패: {client_id} - {e}")
        try:
            await websocket.close(code=1011, reason="Server error")
        except:
            pass

async def heartbeat_manager(websocket: WebSocket, client_id: str):
    """Context7 기반: 하트비트 관리"""
    try:
        while True:
            await asyncio.sleep(15)  # 15초마다 하트비트
            
            await safe_send_message(websocket, {
                "type": "heartbeat",
                "data": {
                    "client_id": client_id,
                    "timestamp": asyncio.get_event_loop().time() * 1000
                }
            })
            
    except asyncio.CancelledError:
        print(f"💓 하트비트 중지: {client_id}")
    except Exception as e:
        print(f"❌ 하트비트 오류: {client_id} - {e}")

async def handle_client_message(websocket: WebSocket, session: DebateSession, data: str, client_id: str):
    """클라이언트 메시지 처리"""
    try:
        message = json.loads(data)
        message_type = message.get("type")
        
        if message_type == "ping":
            # Ping 응답
            await safe_send_message(websocket, {
                "type": "pong",
                "data": {
                    "client_id": client_id,
                    "timestamp": asyncio.get_event_loop().time() * 1000
                }
            })
            
        elif message_type == "sync_request":
            # 상태 동기화 요청 처리
            await handle_sync_request(websocket, session, message.get("data"), client_id)
            
        else:
            print(f"🔍 알 수 없는 메시지 타입: {message_type} from {client_id}")
            
    except json.JSONDecodeError:
        print(f"❌ 잘못된 JSON: {client_id}")
    except Exception as e:
        print(f"❌ 메시지 처리 오류: {client_id} - {e}")

async def handle_sync_request(websocket: WebSocket, session: DebateSession, data: dict, client_id: str):
    """상태 동기화 요청 처리"""
    try:
        await safe_send_message(websocket, {
            "type": "sync_response",
            "data": {
                "current_round": session.current_round,
                "is_active": session.is_active,
                "session_id": session.session_id,
                "client_id": client_id,
                "server_time": asyncio.get_event_loop().time() * 1000
            }
        })
        print(f"🔄 상태 동기화 응답: {client_id}")
        
    except Exception as e:
        print(f"❌ 동기화 응답 실패: {client_id} - {e}")

if __name__ == "__main__":
    import uvicorn
    print("🚀 최종 AI 토론 배틀 아레나")
    print("🌐 http://localhost:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003)