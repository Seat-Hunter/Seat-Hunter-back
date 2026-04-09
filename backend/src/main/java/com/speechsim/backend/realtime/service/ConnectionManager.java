package com.speechsim.backend.realtime.service;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketSession;

import java.util.concurrent.ConcurrentHashMap;
import java.util.Map;

@Component
public class ConnectionManager {

    private final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();

    // 연결 저장
    public void connect(String sessionId, WebSocketSession session) {
        sessions.put(sessionId, session);
        System.out.println("🟢 연결 저장됨: " + sessionId);
    }

    // 연결 가져오기
    public WebSocketSession get(String sessionId) {
        return sessions.get(sessionId);
    }

    // 연결 제거
    public void disconnect(String sessionId) {
        sessions.remove(sessionId);
        System.out.println("🔴 연결 제거됨: " + sessionId);
    }
}