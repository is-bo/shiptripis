package com.shiptrip.shiptrip

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannels(
            listOf(
                channel("messages", R.string.notification_channel_messages),
                channel("deliveries", R.string.notification_channel_deliveries),
                channel("account", R.string.notification_channel_account),
                channel("payments", R.string.notification_channel_payments),
            ),
        )
    }

    private fun channel(id: String, name: Int) = NotificationChannel(
        id,
        getString(name),
        NotificationManager.IMPORTANCE_DEFAULT,
    )
}
