
import org.jetbrains.kotlin.gradle.tasks.KotlinCompile
import com.google.protobuf.gradle.*
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm") version "2.3.0"
    application
    id("java")
    id("idea")
    id("com.google.protobuf") version "0.9.6"
    id("com.github.johnrengelman.shadow") version "8.1.1"
}

group = "io.opentelemetry"
version = "1.0"


val grpcVersion = "1.78.0"
val protobufVersion = "4.33.2"
// Trivy HIGH: CVE-2026-54512/54513 — jackson-databind must be >=2.21.4 (flagd-core pulls 2.21.2).
val jacksonVersion = "2.21.4"
val jacksonAnnotationsVersion = "2.21"

repositories {
    mavenCentral()
    gradlePluginPortal()
}

// Hard floor so flagd-core cannot package jackson-databind 2.21.2 into the image.
configurations.configureEach {
    resolutionStrategy {
        force(
            "com.fasterxml.jackson.core:jackson-core:$jacksonVersion",
            "com.fasterxml.jackson.core:jackson-databind:$jacksonVersion",
            "com.fasterxml.jackson.core:jackson-annotations:$jacksonAnnotationsVersion",
            "com.fasterxml.jackson.dataformat:jackson-dataformat-yaml:$jacksonVersion",
        )
    }
}

dependencies {
    constraints {
        implementation("com.fasterxml.jackson.core:jackson-databind:$jacksonVersion")
    }
    implementation(enforcedPlatform("io.netty:netty-bom:4.1.135.Final"))
    implementation(enforcedPlatform("com.fasterxml.jackson:jackson-bom:$jacksonVersion"))
    implementation("com.google.protobuf:protobuf-java:${protobufVersion}")
    testImplementation(kotlin("test"))
    implementation(kotlin("script-runtime"))
    implementation("org.apache.kafka:kafka-clients:4.1.1")
    implementation("com.google.api.grpc:proto-google-common-protos:2.63.2")
    implementation("io.grpc:grpc-protobuf:${grpcVersion}")
    implementation("io.grpc:grpc-stub:${grpcVersion}")
    implementation("io.grpc:grpc-netty:${grpcVersion}")
    implementation("io.grpc:grpc-services:${grpcVersion}")
    implementation("io.opentelemetry:opentelemetry-api:1.57.0")
    implementation("io.opentelemetry:opentelemetry-sdk:1.57.0")
    implementation("io.opentelemetry:opentelemetry-extension-annotations:1.18.0")
    implementation("org.apache.logging.log4j:log4j-core:2.25.3")
    implementation("org.slf4j:slf4j-api:2.0.17")
    implementation("com.google.protobuf:protobuf-kotlin:${protobufVersion}")
    implementation("dev.openfeature:sdk:1.20.2")
    implementation("dev.openfeature.contrib.providers:flagd:0.13.3")
    implementation("redis.clients:jedis:5.1.2")

    if (JavaVersion.current().isJava9Compatible) {
        // Workaround for @javax.annotation.Generated
        // see: https://github.com/grpc/grpc-java/issues/3633
        implementation("javax.annotation:javax.annotation-api:1.3.2")
    }
}

tasks {
    shadowJar {
        mergeServiceFiles()
    }
}

tasks.test {
    useJUnitPlatform()
}

kotlin {
  compilerOptions {
    jvmTarget.set(JvmTarget.JVM_17)
  }
}

protobuf {
    protoc {
        artifact = "com.google.protobuf:protoc:${protobufVersion}"
    }
    plugins {

        id("grpc") {
            artifact = "io.grpc:protoc-gen-grpc-java:${grpcVersion}"
        }
    }
    generateProtoTasks {
        ofSourceSet("main").forEach {
            it.plugins {
                // Apply the "grpc" plugin whose spec is defined above, without
                // options. Note the braces cannot be omitted, otherwise the
                // plugin will not be added. This is because of the implicit way
                // NamedDomainObjectContainer binds the methods.
                id("grpc") { }
            }
        }
    }
}

application {
    mainClass.set("frauddetection.MainKt")
}

tasks.jar {
    manifest.attributes["Main-Class"] = "frauddetection.MainKt"
}
// Change trail: @hungxqt - 2026-07-21 - Force jackson-databind 2.21.4 for CVE-2026-54512/54513
