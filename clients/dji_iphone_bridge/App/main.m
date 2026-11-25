#import <DJISDK/DJISDK.h>
#import <UIKit/UIKit.h>
#import <arpa/inet.h>
#import <math.h>

static BOOL IsPrivateHost(NSString *host) {
    struct in_addr address;
    if (!host || inet_pton(AF_INET, host.UTF8String, &address) != 1) return NO;
    uint32_t ip = ntohl(address.s_addr);
    return (ip >> 24) == 10 || (ip >> 20) == 0xac1 || (ip >> 16) == 0xc0a8;
}

@interface CameraController : UIViewController
    <DJISDKManagerDelegate, DJIVideoFeedListener, DJIFlightControllerDelegate,
     NSURLSessionWebSocketDelegate>
@property(nonatomic, strong) UILabel *aircraft;
@property(nonatomic, strong) UILabel *telemetry;
@property(nonatomic, strong) UILabel *status;
@property(nonatomic, strong) UITextField *address;
@property(nonatomic, strong) UITextField *code;
@property(nonatomic, strong) UIButton *start;
@property(nonatomic, strong) UIButton *stop;
@property(nonatomic, strong) DJIVideoFeed *feed;
@property(nonatomic, strong) DJIFlightController *flight;
@property(nonatomic, strong) NSURLSession *session;
@property(nonatomic, strong) NSURLSessionWebSocketTask *socket;
@property(nonatomic, strong) dispatch_queue_t videoQueue;
@property(nonatomic, strong) NSMutableArray<NSData *> *pending;
@property(nonatomic) NSUInteger bytes;
@property(nonatomic) BOOL connected;
@property(nonatomic) BOOL sending;
@property(nonatomic) BOOL sentVideo;
@end

@implementation CameraController
- (UILabel *)label:(NSString *)text {
    UILabel *label = [UILabel new];
    label.text = text;
    label.numberOfLines = 0;
    return label;
}

- (UITextField *)field:(NSString *)placeholder secure:(BOOL)secure {
    UITextField *field = [UITextField new];
    field.placeholder = placeholder;
    field.accessibilityLabel = placeholder;
    field.borderStyle = UITextBorderStyleRoundedRect;
    field.autocapitalizationType = UITextAutocapitalizationTypeNone;
    field.autocorrectionType = UITextAutocorrectionTypeNo;
    field.secureTextEntry = secure;
    return field;
}

- (UIButton *)button:(NSString *)title action:(SEL)action {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
    [button setTitle:title forState:UIControlStateNormal];
    [button addTarget:self action:action forControlEvents:UIControlEventTouchUpInside];
    button.enabled = NO;
    return button;
}

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.videoQueue = dispatch_queue_create("org.lifejacket.camera.video", DISPATCH_QUEUE_SERIAL);
    self.pending = [NSMutableArray new];
    self.session = [NSURLSession sessionWithConfiguration:NSURLSessionConfiguration.ephemeralSessionConfiguration
                                                  delegate:self delegateQueue:NSOperationQueue.mainQueue];
    UILabel *title = [self label:@"LifeJacket Camera"];
    title.font = [UIFont preferredFontForTextStyle:UIFontTextStyleLargeTitle];
    self.aircraft = [self label:@"Registering DJI SDK…"];
    self.telemetry = [self label:@"Waiting for aircraft telemetry"];
    self.status = [self label:@"Camera relay stopped"];
    self.address = [self field:@"ws://192.168.x.x:8765/camera" secure:NO];
    self.address.keyboardType = UIKeyboardTypeURL;
    self.code = [self field:@"Pairing code" secure:YES];
    self.start = [self button:@"Start camera relay" action:@selector(startRelay)];
    self.stop = [self button:@"Stop relay" action:@selector(stopRelay)];

    UIStackView *stack = [[UIStackView alloc] initWithArrangedSubviews:
        @[title, self.aircraft, self.telemetry, self.address, self.code, self.start, self.stop, self.status]];
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 12;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:stack];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [stack.topAnchor constraintEqualToAnchor:safe.topAnchor constant:20],
        [stack.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:20],
        [stack.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-20]
    ]];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(inactive:)
        name:UIApplicationWillResignActiveNotification object:nil];

    NSString *key = [NSBundle.mainBundle objectForInfoDictionaryKey:@"DJISDKAppKey"];
    if (key.length == 0 || [key hasPrefix:@"$("]) {
        self.aircraft.text = @"Set DJI_SDK_APP_KEY in the Xcode target before installing.";
        return;
    }
    [DJISDKManager registerAppWithDelegate:self];
}

- (void)appRegisteredWithError:(NSError *)error {
    dispatch_async(dispatch_get_main_queue(), ^{
        self.aircraft.text = error
            ? [NSString stringWithFormat:@"DJI registration failed (code %ld).", (long)error.code]
            : @"Connect the RC-N1 and power on the Mini 2.";
        if (!error) [DJISDKManager startConnectionToProduct];
    });
}

- (void)productConnected:(DJIBaseProduct *)product {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (![product isKindOfClass:DJIAircraft.class]) return;
        [self.feed removeListener:self];
        self.flight.delegate = nil;
        self.flight = ((DJIAircraft *)product).flightController;
        self.flight.delegate = self;
        self.feed = [DJISDKManager videoFeeder].primaryVideoFeed;
        [self.feed addListener:self withQueue:self.videoQueue];
        self.start.enabled = self.feed != nil && !self.stop.enabled;
        self.aircraft.text = [NSString stringWithFormat:@"Connected: %@", product.model ?: @"DJI aircraft"];
    });
}

- (void)productDisconnected {
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.feed removeListener:self];
        self.feed = nil;
        self.flight.delegate = nil;
        self.flight = nil;
        self.start.enabled = NO;
        self.aircraft.text = @"DJI controller disconnected";
        self.telemetry.text = @"Waiting for aircraft telemetry";
        [self stopRelay];
    });
}

- (void)flightController:(DJIFlightController *)flight didUpdateState:(DJIFlightControllerState *)state {
    BOOL motorsOn = state.areMotorsOn;
    float speed = hypotf(state.velocityX, state.velocityY), altitude = state.altitude;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (flight != self.flight) return;
        self.telemetry.text = [NSString stringWithFormat:@"Motors %@ · %.1f m/s · %.1f m relative altitude",
            motorsOn ? @"on" : @"off", speed, altitude];
    });
}

- (void)startRelay {
    [self.view endEditing:YES];
    NSCharacterSet *ws = NSCharacterSet.whitespaceAndNewlineCharacterSet;
    NSURLComponents *url = [NSURLComponents componentsWithString:[self.address.text stringByTrimmingCharactersInSet:ws]];
    NSString *code = [self.code.text stringByTrimmingCharactersInSet:ws];
    if (![url.scheme isEqualToString:@"ws"] || !IsPrivateHost(url.host) || !url.URL
        || url.port.integerValue < 1 || url.port.integerValue > 65535
        || ![url.path isEqualToString:@"/camera"] || url.query || url.fragment || url.user || url.password
        || code.length != 32
        || [code rangeOfString:@"^[A-Za-z0-9_-]{32}$" options:NSRegularExpressionSearch].location == NSNotFound) {
        self.status.text = @"Enter the private relay address and pairing code.";
        return;
    }
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url.URL];
    [request setValue:[@"Bearer " stringByAppendingString:code] forHTTPHeaderField:@"Authorization"];
    self.start.enabled = NO;
    self.stop.enabled = YES;
    self.status.text = @"Connecting to LifeJacket relay…";
    dispatch_async(self.videoQueue, ^{
        NSURLSessionWebSocketTask *task = [self.session webSocketTaskWithRequest:request];
        self.socket = task;
        [task resume];
        [task receiveMessageWithCompletionHandler:^(NSURLSessionWebSocketMessage *message, NSError *error) {
            dispatch_async(self.videoQueue, ^{
                if (self.socket == task) [self endSocket:@"Relay disconnected. Check pairing and Wi-Fi."];
            });
        }];
    });
}

- (void)URLSession:(NSURLSession *)session webSocketTask:(NSURLSessionWebSocketTask *)task
    didOpenWithProtocol:(NSString *)protocol {
    dispatch_async(self.videoQueue, ^{
        if (self.socket != task) return;
        self.connected = YES;
        dispatch_async(dispatch_get_main_queue(), ^{
            self.status.text = @"Paired. Waiting for DJI camera data…";
            UIApplication.sharedApplication.idleTimerDisabled = YES;
        });
    });
}

- (void)videoFeed:(DJIVideoFeed *)feed didUpdateVideoData:(NSData *)data {
    // This callback runs on the serial video queue.
    if (!self.connected || !data.length) return;
    if (data.length > 512 * 1024 || self.bytes + data.length > 1024 * 1024 || self.pending.count >= 64) {
        [self endSocket:@"Wi-Fi could not keep up. Restart the relay."];
        return;
    }
    [self.pending addObject:[data copy]];
    self.bytes += data.length;
    [self sendNext];
}

- (void)sendNext {
    if (!self.connected || self.sending || !self.pending.count) return;
    self.sending = YES;
    NSData *data = self.pending.firstObject;
    [self.pending removeObjectAtIndex:0];
    NSURLSessionWebSocketTask *task = self.socket;
    [task sendMessage:[[NSURLSessionWebSocketMessage alloc] initWithData:data] completionHandler:^(NSError *error) {
        dispatch_async(self.videoQueue, ^{
            if (self.socket != task) return;
            self.bytes -= data.length;
            self.sending = NO;
            if (error) {
                [self endSocket:@"Video send failed. Check Wi-Fi and restart."];
                return;
            }
            if (!self.sentVideo) {
                self.sentVideo = YES;
                dispatch_async(dispatch_get_main_queue(), ^{
                    self.status.text = @"Sending camera data. Check the LifeJacket preview.";
                });
            }
            [self sendNext];
        });
    }];
}

- (void)inactive:(NSNotification *)notification {
    [self stopRelay];
}

- (void)stopRelay {
    dispatch_async(self.videoQueue, ^{ [self endSocket:@"Camera relay stopped"]; });
}

- (void)endSocket:(NSString *)message {
    [self.socket cancelWithCloseCode:NSURLSessionWebSocketCloseCodeNormalClosure reason:nil];
    self.socket = nil;
    self.connected = self.sending = self.sentVideo = NO;
    self.bytes = 0;
    [self.pending removeAllObjects];
    dispatch_async(dispatch_get_main_queue(), ^{
        self.start.enabled = self.feed != nil;
        self.stop.enabled = NO;
        self.status.text = message;
        UIApplication.sharedApplication.idleTimerDisabled = NO;
    });
}
@end

@interface CameraAppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation CameraAppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [CameraController new];
    [self.window makeKeyAndVisible];
    return YES;
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass(CameraAppDelegate.class));
    }
}
