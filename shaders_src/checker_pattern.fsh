//
//  checker_pattern.fsh
//
//  Created by bend on 15/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

// Material spreadsheet uniforms
uniform mediump vec3 mu_Colour;

// Vertex shader outputs
varying highp vec2 v_TexCoord0;

void main()
{
	mediump vec3 Color1 = vec3( 0.0, 0.0, 0.0 );
	mediump vec3 AvgColor = (Color1 + mu_Colour) / 2.0;
	mediump float Frequency = 10.0;

	mediump vec3 color;
	
	// Determine the width of the projection of one pixel into s-t space
	mediump vec2 fw = vec2( 0.0 );//fwidth(v_TexCoord0);

	// Determine the amount of fuzziness
	mediump vec2 fuzz = fw * Frequency * 2.0;

	mediump float fuzzMax = max(fuzz.s, fuzz.t);

	// Determine the position in the checkerboard pattern
	mediump vec2 checkPos = fract(v_TexCoord0 * Frequency);

	if( fuzzMax < 0.5 )
	{
		// If the filter width is small enough, compute the pattern color
		mediump vec2 p = smoothstep(vec2(0.5), fuzz + vec2(0.5), checkPos) +
		(1.0 - smoothstep(vec2(0.0), fuzz, checkPos));

		color = mix(Color1, mu_Colour, p.x * p.y + (1.0 - p.x) * (1.0 - p.y));

		// Fade in the average color when we get close to the limit
		color = mix(color, AvgColor, smoothstep(0.125, 0.5, fuzzMax));
	}
	else
	{
		// Otherwise, use only the average color
		color = AvgColor;
	}

	gl_FragColor = vec4(color, 1.0);
}

