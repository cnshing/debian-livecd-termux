// YouTube chooses a codec by asking the page's media APIs what is supported.
{
  const av1 = type => /\bav01\b|\bav1\b/i.test(String(type));
  const supported = MediaSource.isTypeSupported.bind(MediaSource);
  MediaSource.isTypeSupported = type => !av1(type) && supported(type);
  const canPlay = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function (type) {
    return av1(type) ? '' : canPlay.call(this, type);
  };
  const decodingInfo = MediaCapabilities.prototype.decodingInfo;
  MediaCapabilities.prototype.decodingInfo = function (config) {
    return av1(config?.video?.contentType)
      ? Promise.resolve({ supported: false, smooth: false, powerEfficient: false })
      : decodingInfo.call(this, config);
  };
}
