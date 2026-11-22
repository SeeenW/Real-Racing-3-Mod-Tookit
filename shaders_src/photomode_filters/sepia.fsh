//
//  sepia.vsh
//
//  Created by bend on 06/09/13.
//  Copyright EA 2013. All rights reserved.
//

// Use EXT_shader_framebuffer_fetch extension if available
//
//   Defines FRAMEBUFFER_RGBA as the source fragment colour
//

#ifdef FRAMEBUFFER_FETCH
	#extension GL_EXT_shader_framebuffer_fetch : require
	#define FRAMEBUFFER_RGBA gl_LastFragData[0]
#else
	uniform lowp sampler2D s_Texture0;		// Screen texture
	varying lowp vec2 v_TexCoord;
	#define FRAMEBUFFER_RGBA texture2D(s_Texture0, v_TexCoord)
#endif

void main()
{
	lowp vec3 colour = FRAMEBUFFER_RGBA.rgb;
	
	highp vec3 sepia;
	sepia.r = min( (colour.r * 0.393) + (colour.g * 0.769) + (colour.b * 0.189), 1.0 );
	sepia.g = min( (colour.r * 0.349) + (colour.g * 0.686) + (colour.b * 0.168), 1.0 );
	sepia.b = min( (colour.r * 0.272) + (colour.g * 0.534) + (colour.b * 0.131), 1.0 );

	gl_FragColor = vec4( sepia, 1.0 );
}

