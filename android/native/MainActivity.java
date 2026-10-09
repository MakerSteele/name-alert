package com.makersteele.namealert;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(NameAlertPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
