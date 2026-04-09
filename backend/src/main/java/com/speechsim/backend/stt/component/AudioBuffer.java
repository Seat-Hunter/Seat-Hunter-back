package com.speechsim.backend.stt.component;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Component
public class AudioBuffer {

    private final List<byte[]> buffer = new ArrayList<>();

    public void add(byte[] chunk) {
        buffer.add(chunk);
    }

    public List<byte[]> flush() {
        List<byte[]> copy = new ArrayList<>(buffer);
        buffer.clear();
        return copy;
    }

    public int size() {
        return buffer.size();
    }
}