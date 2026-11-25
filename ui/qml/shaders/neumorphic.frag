#version 440
// One rounded surface plus CSS-equivalent box-shadows.
//
// CSS box-shadow semantics are reproduced analytically: a shadow is the
// (offset, spread) rounded rectangle convolved with a Gaussian of
// sigma = blur / 2. The convolution is approximated with the error function
// of the rounded-rect signed distance, which is exact on straight edges.
//   * outer shadows are painted outside the border box only (CSS clips them);
//   * inset shadows darken the inside, outside a shifted "hole" rectangle;
//   * in CSS the first listed shadow is painted on top: slot 1 is the top.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 itemSize;
    vec4 bodyRect;        // x, y, width, height of the border box in item px
    float radius;
    vec4 surfaceColor;
    vec4 outer1;          // offset.x, offset.y, blur, spread
    vec4 outer1Color;
    vec4 outer2;
    vec4 outer2Color;
    vec4 outer3;
    vec4 outer3Color;
    vec4 outer4;
    vec4 outer4Color;
    vec4 inset1;          // offset.x, offset.y, blur, spread
    vec4 inset1Color;
    vec4 inset2;
    vec4 inset2Color;
};

float sdRoundRect(vec2 p, vec2 halfSize, float r) {
    r = min(r, min(halfSize.x, halfSize.y));
    vec2 q = abs(p) - halfSize + vec2(r);
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

// Abramowitz & Stegun 7.1.27, |error| < 5e-4.
float erfApprox(float x) {
    float s = sign(x);
    float a = abs(x);
    float t = 1.0 + a * (0.278393 + a * (0.230389 + a * (0.000972 + a * 0.078108)));
    t *= t;
    return s * (1.0 - 1.0 / (t * t));
}

// Coverage of a rounded rect blurred with a Gaussian (CSS blur radius).
float blurredCoverage(float sd, float blur) {
    if (blur < 0.5) {
        return clamp(0.5 - sd, 0.0, 1.0);
    }
    float sigma = blur * 0.5;
    return 0.5 * (1.0 - erfApprox(sd / (sigma * 1.41421356)));
}

vec4 over(vec4 top, vec4 bottom) {
    return top + bottom * (1.0 - top.a);
}

vec4 outerShadow(vec2 p, vec2 center, vec2 halfSize, vec4 shadow, vec4 color) {
    if (color.a <= 0.0) {
        return vec4(0.0);
    }
    vec2 h = max(halfSize + vec2(shadow.w), vec2(0.0));
    float sd = sdRoundRect(p - center - shadow.xy, h, max(radius + shadow.w, 0.0));
    float a = color.a * blurredCoverage(sd, shadow.z);
    return vec4(color.rgb * a, a);
}

vec3 insetShadow(vec3 rgb, vec2 p, vec2 center, vec2 halfSize, vec4 shadow, vec4 color) {
    if (color.a <= 0.0) {
        return rgb;
    }
    vec2 h = max(halfSize - vec2(shadow.w), vec2(0.0));
    float sd = sdRoundRect(p - center - shadow.xy, h, max(radius - shadow.w, 0.0));
    float a = color.a * (1.0 - blurredCoverage(sd, shadow.z));
    return mix(rgb, color.rgb, a);
}

void main() {
    vec2 p = qt_TexCoord0 * itemSize;
    vec2 halfSize = bodyRect.zw * 0.5;
    vec2 center = bodyRect.xy + halfSize;

    float bodySd = sdRoundRect(p - center, halfSize, radius);
    float bodyCoverage = clamp(0.5 - bodySd, 0.0, 1.0);

    vec4 shadows = outerShadow(p, center, halfSize, outer4, outer4Color);
    shadows = over(outerShadow(p, center, halfSize, outer3, outer3Color), shadows);
    shadows = over(outerShadow(p, center, halfSize, outer2, outer2Color), shadows);
    shadows = over(outerShadow(p, center, halfSize, outer1, outer1Color), shadows);
    shadows *= 1.0 - bodyCoverage;

    vec3 rgb = surfaceColor.rgb;
    rgb = insetShadow(rgb, p, center, halfSize, inset2, inset2Color);
    rgb = insetShadow(rgb, p, center, halfSize, inset1, inset1Color);
    vec4 body = vec4(rgb, 1.0) * (surfaceColor.a * bodyCoverage);

    fragColor = over(body, shadows) * qt_Opacity;
}
