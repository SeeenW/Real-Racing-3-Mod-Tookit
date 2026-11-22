
// Colour adjustment functions

// The RGB to HSV (and back) conversion code is described here:
// http://lolengine.net/blog/2013/07/27/rgb-to-hsv-in-glsl
lowp vec3 rgb2hsv( in lowp vec3 rgb )
{
	highp vec4 K = vec4( 0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0 );
	highp vec4 p = mix( vec4( rgb.bg, K.wz ), vec4( rgb.gb, K.xy ), step( rgb.b, rgb.g ) );
	highp vec4 q = mix( vec4( p.xyw, rgb.r ), vec4( rgb.r, p.yzx ), step( p.x, rgb.r ) );

	highp float d = q.x - min( q.w, q.y );
	highp float e = 1.0e-10;

	return vec3( abs( q.z + (q.w - q.y) / (6.0 * d + e) ), d / (q.x + e), q.x );
}

lowp vec3 hsv2rgb( in lowp vec3 hsv )
{
	highp vec4 K = vec4( 1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0 );
	highp vec3 p = abs( fract( hsv.xxx + K.xyz ) * 6.0 - K.www );

	return hsv.z * mix( K.xxx, clamp( p - K.xxx, 0.0, 1.0 ), hsv.y );
}

// brightness => [-1, 1] (default: 0)
void adjust_brightness( inout lowp vec3 colour, in lowp vec3 brightness )
{
	colour += brightness;
}

// contrast => [0, 4] (default: 1)
void adjust_contrast( inout lowp vec3 colour, in lowp vec3 contrast )
{
	colour = ((colour - 0.5) * contrast) + 0.5;
}

// rgb modulate => [0, 4] (default: 1)
void adjust_rgb( inout lowp vec3 colour, in lowp vec3 rgbModulate )
{
	colour *= rgbModulate;
}

// exposure => [-10, 10] (default: 0)
void adjust_exposure( inout lowp vec3 colour, in lowp float exposure )
{
	colour *= pow( 2.0, exposure );
}

// saturation => [0, 4] (default: 1)
void adjust_saturation( inout lowp vec3 colour, in lowp float saturation )
{
	// Values from "Graphics Shaders: Theory and Practice" by Bailey and Cunningham
	const mediump vec3 luminanceWeighting = vec3( 0.2125, 0.7154, 0.0721 );
	lowp float luminance = dot( colour, luminanceWeighting );
	lowp vec3 greyScaleColor = vec3( luminance );
	colour = mix( greyScaleColor, colour, saturation );
}

// gamma => [0, 3] (default: 1)
void adjust_gamma( inout lowp vec3 colour, in lowp float gamma )
{
	colour = pow( colour, vec3( gamma ) );
}

// levels => [0, 1] for all values (defaults: 0, 1, 1, 0, 1)
void adjust_levels( inout lowp vec3 colour, in lowp vec3 inputMin,
											in lowp vec3 gamma,
											in lowp vec3 inputMax,
											in lowp vec3 outputMin,
											in lowp vec3 outputMax )
{
	// Input range
	colour = min( max( colour - inputMin, vec3( 0.0 ) ) / (inputMax - inputMin), vec3( 1.0 ) );
	// Gamma correction
	colour = pow( colour, 1.0 / gamma );
	// Output range
	colour = mix( outputMin, outputMax, colour );
}

// hue => [0, 360] (default: 0)
void adjust_hue( inout lowp vec3 colour, in mediump float hueAdjust )
{
	const highp vec3 kRGBToYPrime	= vec3( 0.299, 0.587, 0.114 );
	const highp vec3 kRGBToI		= vec3( 0.595716, -0.274453, -0.321263 );
	const highp vec3 kRGBToQ		= vec3( 0.211456, -0.522591, 0.31135 );

	const highp vec3 kYIQToR		= vec3( 1.0, 0.9563, 0.6210 );
	const highp vec3 kYIQToG		= vec3( 1.0, -0.2721, -0.6474 );
	const highp vec3 kYIQToB		= vec3( 1.0, -1.1070, 1.7046 );

	// Convert to YIQ
	highp float YPrime	= dot( colour, kRGBToYPrime );
	highp float I		= dot( colour, kRGBToI );
	highp float Q		= dot( colour, kRGBToQ );

	// Calculate the hue and chroma
	highp float hue		= atan( Q, I );
	highp float chroma	= sqrt( I * I + Q * Q );

	// Make the user's adjustments
	hue += (-hueAdjust);	//why negative rotation?

	// Convert back to YIQ
	Q = chroma * sin( hue );
	I = chroma * cos( hue );

	// Convert back to RGB
	highp vec3 yIQ = vec3( YPrime, I, Q );
	colour.r = dot( yIQ, kYIQToR );
	colour.g = dot( yIQ, kYIQToG );
	colour.b = dot( yIQ, kYIQToB );
}

void adjust_hsv( inout lowp vec3 colour, in mediump float hue, in mediump float saturation, in mediump float value )
{
	lowp vec3 hsv = rgb2hsv( colour );
	hsv.x += hue / 360.0;
	hsv.y += saturation / 100.0;
	hsv.z += value / 100.0;
	colour = hsv2rgb( hsv );
}

