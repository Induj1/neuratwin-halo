#include <Arduino.h>
#include <ArduinoJson.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <esp_timer.h>
#include "halo_config.h"
#include <math.h>

struct Wave { double sum=0,sq=0; unsigned n=0; uint32_t low=99999,high=0; };
Wave waves[4]; const int adcPins[4]={PRIMARY_ADC,SECONDARY_ADC,CURRENT_ADC,PRIMARY_CURRENT_ADC};
bool pinsReady=false,adcReady=false,relaysReady=false,states[4]={false,false,false,false};
bool hostPermit=false,validChannels=false; double currentScale=0,noiseMv=0,surfaceOffset=0,currentLimit=0,surfaceLimit=0,secondaryScale=0,nominalV=0;
double lastCurrent=NAN,lastSurface=NAN,lastSecondary=NAN; uint32_t lastHost=0,lastFrame=0; uint64_t sequence=0; String bootId,line;
OneWire* oneWire=nullptr; DallasTemperature* temperatures=nullptr;
uint64_t uptime(){return esp_timer_get_time()/1000;}
bool adcPin(int p){
#if CONFIG_IDF_TARGET_ESP32
 return p>=32&&p<=39;
#elif CONFIG_IDF_TARGET_ESP32S3
 return p>=1&&p<=10;
#else
 return false;
#endif
}
bool outputPin(int p){
#if CONFIG_IDF_TARGET_ESP32
 return (p>=0&&p<=5)||(p>=12&&p<=19)||p==21||p==22||p==23||p==25||p==26||p==27||p==32||p==33;
#elif CONFIG_IDF_TARGET_ESP32S3
 return (p>=0&&p<=18)||p==21||(p>=38&&p<=42)||p==47||p==48;
#else
 return false;
#endif
}
bool validatePins(){if(!PINMAP_VERIFIED)return false;int p[8]={RELAY_PINS[0],RELAY_PINS[1],RELAY_PINS[2],RELAY_PINS[3],PRIMARY_ADC,SECONDARY_ADC,CURRENT_ADC,SURFACE_DATA};for(int i=0;i<8;i++){if(p[i]<0)return false;for(int j=0;j<i;j++)if(p[i]==p[j])return false;}if(PRIMARY_CURRENT_ADC>=0){if(!adcPin(PRIMARY_CURRENT_ADC))return false;for(int i=0;i<8;i++)if(p[i]==PRIMARY_CURRENT_ADC)return false;}for(int i=0;i<4;i++)if(!outputPin(RELAY_PINS[i]))return false;return adcPin(PRIMARY_ADC)&&adcPin(SECONDARY_ADC)&&adcPin(CURRENT_ADC)&&outputPin(SURFACE_DATA);}
void off(){for(int i=0;i<4;i++){states[i]=false;if(relaysReady)digitalWrite(RELAY_PINS[i],RELAY_ACTIVE_LOW?HIGH:LOW);}}
void safety(){if(!hostPermit||!validChannels||millis()-lastHost>HOST_TIMEOUT_MS||!isfinite(lastCurrent)||!isfinite(lastSurface)||!isfinite(lastSecondary)||lastCurrent>currentLimit||lastSurface>=surfaceLimit||lastSecondary>nominalV*1.25)off();}
void emit(JsonDocument& d){serializeJson(d,Serial);Serial.println();}
void hello(const String& nonce="") {JsonDocument d;d["type"]="hello";d["nonce"]=nonce;d["protocol"]=1;d["device_id"]=DEVICE_ID;d["boot_id"]=bootId;d["uptime_ms"]=uptime();d["chip"]=ESP.getChipModel();d["pinmap_verified"]=pinsReady;d["adc_verified"]=adcReady;d["relay_verified"]=relaysReady;d["control_compiled"]=PHYSICAL_CONTROL_ENABLED;d["active_low"]=RELAY_ACTIVE_LOW;JsonArray p=d["relay_pins"].to<JsonArray>();for(auto v:RELAY_PINS)p.add(v);d["primary_adc_pin"]=PRIMARY_ADC;d["secondary_adc_pin"]=SECONDARY_ADC;d["current_adc_pin"]=CURRENT_ADC;d["primary_current_adc_pin"]=PRIMARY_CURRENT_ADC;d["temperature_pin"]=SURFACE_DATA;emit(d);}
void command(const String& text){JsonDocument d;if(deserializeJson(d,text))return;const String type=d["type"]|"";if(type=="hello"){hello(d["nonce"]|"");return;}
 if(type=="heartbeat"){lastHost=millis();hostPermit=d["permit"]|false;currentScale=d["current_a_per_mv"]|0.;secondaryScale=d["secondary_v_per_mv"]|0.;noiseMv=d["current_noise_mv"]|0.;surfaceOffset=d["surface_offset_c"]|0.;currentLimit=d["current_limit_a"]|0.;surfaceLimit=d["surface_limit_c"]|0.;nominalV=d["nominal_secondary_v"]|0.;if(!isfinite(currentLimit)||currentLimit<=0||currentLimit>1||!isfinite(surfaceLimit)||surfaceLimit<30||surfaceLimit>80||!isfinite(currentScale)||currentScale<=0||!isfinite(secondaryScale)||secondaryScale<=0||nominalV<=0||nominalV>24)hostPermit=false;safety();return;}
 if(type!="command")return;
 bool requested[4],enabling=false;bool shape=d["states"].is<JsonArray>()&&d["states"].size()==4;
 for(int i=0;i<4;i++){if(!d["states"][i].is<bool>())shape=false;requested[i]=d["states"][i]|false;enabling|=requested[i];}
 safety();bool okay=shape&&!requested[3];String reason="";uint64_t deadline=d["deadline_uptime_ms"]|uint64_t(0);double projected=0;
 for(int i=0;i<4;i++){double r=d["resistor_ohms"][i]|0.;if(requested[i]){if(r<10||r>1000||!isfinite(r))okay=false;else projected+=lastSecondary/r;}}
 if(enabling&&(!PHYSICAL_CONTROL_ENABLED||!relaysReady||!adcReady||!hostPermit||!validChannels||millis()-lastHost>HOST_TIMEOUT_MS||deadline<=uptime()||deadline>uptime()+5000||!isfinite(projected)||projected>currentLimit||lastCurrent>currentLimit||lastSurface>=surfaceLimit||lastSecondary>nominalV*1.25))okay=false;
 if(okay&&relaysReady){for(int i=0;i<4;i++){states[i]=requested[i];digitalWrite(RELAY_PINS[i],states[i]?(RELAY_ACTIVE_LOW?LOW:HIGH):(RELAY_ACTIVE_LOW?HIGH:LOW));}}
 else {off();okay=false;reason="Firmware control gate rejected command; outputs requested OFF.";}
 JsonDocument a;a["type"]="ack";a["id"]=d["id"]|"";a["accepted"]=okay;a["reason"]=reason;JsonArray arr=a["states"].to<JsonArray>();for(bool s:states)arr.add(s);emit(a);
}
void receive(){while(Serial.available()){char c=Serial.read();if(c=='\n'){command(line);line="";}else if(c!='\r'){if(line.length()<2048)line+=c;else line="";}}}
void sample(){
 for(auto &w:waves)w=Wave();bool overrun=false;uint32_t start=micros(),next=start;
 if(adcReady)while(uint32_t(micros()-start)<200000){if(int32_t(micros()-next)<0){receive();safety();delayMicroseconds(30);continue;}if(uint32_t(micros()-next)>500)overrun=true;next+=500;for(int j=0;j<4;j++){if(adcPins[j]<0)continue;uint32_t v=analogReadMilliVolts(adcPins[j]);auto &w=waves[j];w.sum+=v;w.sq+=double(v)*v;w.n++;w.low=min(w.low,v);w.high=max(w.high,v);}}
 JsonDocument d;d["type"]="telemetry_raw";d["device_id"]=DEVICE_ID;d["boot_id"]=bootId;d["sequence"]=sequence++;d["relay_output_configured"]=relaysReady;d["uptime_ms"]=uptime();JsonArray flags=d["quality_flags"].to<JsonArray>();if(!pinsReady)flags.add("pinmap_unverified");if(!adcReady)flags.add("adc_unverified");if(overrun)flags.add("sampling_overrun");
 double rms[4]={NAN,NAN,NAN,NAN};const char* names[]={"primary","secondary","current","primary_current"};validChannels=adcReady&&!overrun;
 for(int j=0;j<4;j++){auto &w=waves[j];String key=names[j];if(w.n){rms[j]=sqrt(max(0.,w.sq/w.n-pow(w.sum/w.n,2)));d[key+"_rms_mv"]=rms[j];d[key+"_bias_mv"]=w.sum/w.n;d[key+"_min_mv"]=w.low;d[key+"_max_mv"]=w.high;if(w.low<150||w.high>2900){flags.add(key+"_adc_range");validChannels=false;}}else d[key+"_rms_mv"]=nullptr;}d["sample_count"]=waves[0].n;d["window_us"]=micros()-start;
 float temp=temperatures?temperatures->getTempCByIndex(0):DEVICE_DISCONNECTED_C;
 if(temp==DEVICE_DISCONNECTED_C||temp==85||!isfinite(temp)||temp< -55||temp>125){d["surface_raw_c"]=nullptr;flags.add("surface_invalid");validChannels=false;lastSurface=NAN;}else {d["surface_raw_c"]=temp;lastSurface=temp+surfaceOffset;}
 lastCurrent=isfinite(rms[2])&&currentScale>0?sqrt(max(0.,rms[2]*rms[2]-noiseMv*noiseMv))*currentScale:NAN;lastSecondary=isfinite(rms[1])&&secondaryScale>0?rms[1]*secondaryScale:NAN;
 safety();JsonArray a=d["relay_states"].to<JsonArray>();for(bool s:states)a.add(s);emit(d);if(temperatures)temperatures->requestTemperatures();
}
void setup(){Serial.begin(115200);line.reserve(2048);bootId=String(esp_random(),HEX)+String(esp_random(),HEX);pinsReady=validatePins();adcReady=pinsReady&&ADC_INTERFACES_VERIFIED;relaysReady=pinsReady&&RELAY_POLARITY_VERIFIED;
 if(relaysReady){for(int p:RELAY_PINS){digitalWrite(p,RELAY_ACTIVE_LOW?HIGH:LOW);pinMode(p,OUTPUT);}off();}
 if(adcReady){analogReadResolution(12);for(int p:adcPins)if(p>=0)analogSetPinAttenuation(p,ADC_11db);}
 if(pinsReady){oneWire=new OneWire(SURFACE_DATA);temperatures=new DallasTemperature(oneWire);temperatures->begin();temperatures->setResolution(12);temperatures->setWaitForConversion(false);temperatures->requestTemperatures();}hello();
}
void loop(){receive();safety();if(millis()-lastFrame>=1000){lastFrame=millis();sample();}delay(1);}
