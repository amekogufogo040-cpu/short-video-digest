import Foundation
import ImageIO
import Vision

guard CommandLine.arguments.count >= 2 else {
    fputs("usage: ocr_image_text.swift <image> [<image> ...]\n", stderr)
    exit(2)
}

var output: [String: [[String: Any]]] = [:]
for path in CommandLine.arguments.dropFirst() {
    let imageURL = URL(fileURLWithPath: path)
    guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        output[path] = []
        continue
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    request.minimumTextHeight = 0.012

    do {
        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        try handler.perform([request])
        output[path] = (request.results ?? []).compactMap { observation -> [String: Any]? in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            let box = observation.boundingBox
            return [
                "text": candidate.string,
                "confidence": candidate.confidence,
                "x": box.minX,
                "y": box.minY,
                "width": box.width,
                "height": box.height,
            ]
        }
    } catch {
        output[path] = []
    }
}

do {
    let data = try JSONSerialization.data(withJSONObject: output, options: [])
    print(String(data: data, encoding: .utf8) ?? "{}")
} catch {
    fputs("ocr failed: \(error)\n", stderr)
    exit(1)
}
