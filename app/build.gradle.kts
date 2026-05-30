plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.kiomet.webview"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.kiomet.webview"
        minSdk = 24
        targetSdk = 35
        versionCode = 19
        versionName = "1.18"
    }

    signingConfigs {
        create("fixed") {
            storeFile = file("keystore.p12")
            storePassword = "android123"
            keyAlias = "kiomet-debug"
            keyPassword = "android123"
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("fixed")
        }
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.core:core-ktx:1.15.0")
}